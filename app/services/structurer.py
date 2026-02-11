"""JSON structuring service using LLM model.

Key improvements over the original version
-------------------------------------------
1.  Every prompt includes a FILLED-IN EXAMPLE so the LLM sees the exact
    key names it must use (eliminates schema-drift / invented keys).
2.  A FIELD-MAPPING GUIDE explains what each field means in plain language
    (prevents tax-rate → quantity confusion, price → tax_amount, etc.).
3.  A robust post-processing pipeline (rename wrong keys, fix registrations
    format, coerce string numbers, unwrap accidental arrays) runs BEFORE
    Pydantic validation — salvaging output the old code silently dropped.
4.  Markdown fences, JS comments, and trailing commas are stripped
    automatically before JSON.loads().
"""
import json
import logging
import time
import re
from pathlib import Path
from typing import Optional, Tuple, List, Any
from pydantic import ValidationError
from app.config import STRUCTURING_MODEL, JSON_DIR
from app.services.ollama_client import structuring_client
from app.schemas import (
    DocumentSchema,
    MultiInvoiceOutput,
    get_json_template,
    get_multi_invoice_template,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Filled-in example — the LLM sees exactly what correct output looks like
# ═══════════════════════════════════════════════════════════════════════════

EXAMPLE_INPUT = """INVOICE #INV-2024-0056
Date: January 15, 2024   Due: February 15, 2024
From: Acme Corp, 123 Main St, NY 10001, Phone: 555-0100, billing@acme.com, VAT: US123456789
To: John Smith (CUST-042), 456 Oak Ave, LA 90001
1. Widget A (WA-100)  Qty 3 x 29.99 = 89.97
2. Widget B (WB-200)  Qty 1 x 49.99 = 49.99
Subtotal: 139.96  Tax 8%: 11.20  Total: 151.16
Payment: Bank transfer to ACC-1234"""

EXAMPLE_OUTPUT = """{
  "document": {
    "type": "invoice",
    "category": null,
    "subcategory": null,
    "locale": {"language": "en", "currency": "USD", "country": "US"},
    "identifiers": {"document_number": "INV-2024-0056", "reference_numbers": []},
    "dates": {"issue_date": "2024-01-15", "due_date": "2024-02-15", "payment_date": null, "time": null},
    "status": {"payment_status": null}
  },
  "parties": {
    "supplier": {
      "name": "Acme Corp",
      "address": "123 Main St, NY 10001",
      "email": "billing@acme.com",
      "phone": "555-0100",
      "website": null,
      "registrations": [{"type": "VAT", "value": "US123456789"}],
      "payment_details": ["Bank transfer to ACC-1234"]
    },
    "customer": {
      "name": "John Smith",
      "customer_id": "CUST-042",
      "address": "456 Oak Ave, LA 90001",
      "billing_address": null,
      "shipping_address": null,
      "company_registrations": []
    }
  },
  "line_items": [
    {"line_no": 1, "product_code": "WA-100", "description": "Widget A", "quantity": 3, "unit_measure": null, "unit_price": 29.99, "line_total": 89.97, "tax_rate": null, "tax_amount": null},
    {"line_no": 2, "product_code": "WB-200", "description": "Widget B", "quantity": 1, "unit_measure": null, "unit_price": 49.99, "line_total": 49.99, "tax_rate": null, "tax_amount": null}
  ],
  "totals": {"net_amount": 139.96, "tax_amount": 11.20, "gross_amount": 151.16, "tip_amount": null},
  "taxes": [{"code": null, "rate": 8, "base": 139.96, "amount": 11.20}],
  "extraction_metadata": {"fields": {}},
  "page_start": 1,
  "page_end": 1
}"""

# ═══════════════════════════════════════════════════════════════════════════
# Field-mapping cheat-sheet — appended to every prompt
# ═══════════════════════════════════════════════════════════════════════════

FIELD_GUIDE = """
FIELD MAPPING GUIDE — use these EXACT key names:
- document.identifiers.document_number → invoice/receipt/bill/order/PO number
- document.dates.issue_date → document date (YYYY-MM-DD)
- document.dates.due_date → payment due date (YYYY-MM-DD)
- document.locale.currency → 3-letter ISO code: CHF, USD, EUR, GBP …
- parties.supplier → the seller / vendor / store / company issuing the document
- parties.customer → the buyer / client receiving goods/services
- parties.supplier.registrations → VAT/tax IDs as [{"type":"VAT","value":"CHE-123"}]
- parties.supplier.payment_details → bank/payment info as ["string", …]
- line_items — one object per product/service line with SEPARATE fields:
    description  = product/service name ONLY (not the whole line)
    quantity     = unit count or weight (a number like 1, 3, 0.5 kg — NEVER a tax rate)
    unit_price   = price for ONE unit
    line_total   = total for this line (qty × price — copy from text, do NOT calculate)
    tax_rate     = VAT/tax PERCENTAGE for this line (e.g. 7.7) — NOT a price
    tax_amount   = tax in currency for this line — NOT a product price
- totals.net_amount   → subtotal before tax
- totals.tax_amount   → total tax
- totals.gross_amount → final total including tax
- taxes → one entry per tax rate with rate, base, amount

CRITICAL WARNINGS:
- quantity is a COUNT (1, 2, 3, 0.5 kg). Tax rates like 2.5% or 7.7% are NOT quantities.
- tax_amount is a CURRENCY amount. A product price is NOT a tax_amount.
- Do NOT put the entire text line into "description". Split numbers into their own fields.
- Keep descriptions in their ORIGINAL language — do NOT translate.
- A cashier/clerk name is NOT the customer name.
- Rounding adjustments go into totals, not as a line item.
"""

# ═══════════════════════════════════════════════════════════════════════════
# Prompt builders
# ═══════════════════════════════════════════════════════════════════════════


def get_single_page_prompt(extracted_text: str, page_number: int) -> str:
    """Build the prompt for structuring a single page into JSON."""
    template = get_json_template()

    return f"""You must extract structured data from document text into JSON.

=== EXAMPLE ===
INPUT TEXT:
{EXAMPLE_INPUT}

OUTPUT JSON:
{EXAMPLE_OUTPUT}
=== END EXAMPLE ===

Now extract from THIS text. Use the EXACT same JSON key names as the example.

TEXT (page {page_number}):
{extracted_text}

{FIELD_GUIDE}

RULES:
- Output ONLY valid JSON — no markdown fences, no comments, no explanations
- Use the EXACT key names shown in the template — do NOT invent new keys
- Copy numbers exactly as they appear in the text — do NOT calculate or infer
- If a value is missing, use null (or [] for arrays)
- Dates as YYYY-MM-DD, currency as ISO 4217 (CHF, USD, EUR …)
- registrations = [{{"type":"…","value":"…"}}] — never plain strings
- page_start = {page_number}, page_end = {page_number}

TEMPLATE (fill in every key):
{template}

JSON:"""


def get_single_page_repair_prompt(
    invalid_json: str, error_message: str, page_number: int
) -> str:
    """Build a repair prompt for invalid single-page JSON."""
    template = get_json_template()

    return f"""The following JSON has errors. Fix it to match the template EXACTLY.

ERROR: {error_message}

BROKEN JSON:
{invalid_json}

TEMPLATE (every key must exist with correct types):
{template}

FIX RULES:
- Return ONLY valid JSON — no markdown, no comments
- Use EXACTLY the key names in the template — do NOT rename or add keys
- registrations = [{{"type":"…","value":"…"}}] (objects, not strings)
- payment_details = ["…"] (strings)
- All numbers must be numeric (9.77), not strings
- Missing values = null, missing arrays = []
- page_start = {page_number}, page_end = {page_number}

FIXED JSON:"""


def get_structuring_prompt(extracted_text: str, page_count: int = 1) -> str:
    """Build the prompt for multi-page / multi-invoice structuring."""
    template = get_multi_invoice_template()

    return f"""Extract all invoices/receipts from this {page_count}-page document.

=== EXAMPLE ===
INPUT TEXT:
{EXAMPLE_INPUT}

OUTPUT JSON:
{{"invoices": [{EXAMPLE_OUTPUT}]}}
=== END EXAMPLE ===

Now extract from THIS text. Use the EXACT same JSON key names.

TEXT ({page_count} pages):
{extracted_text}

{FIELD_GUIDE}

RULES:
- Output ONLY valid JSON — no markdown fences, no comments, no explanations
- Use the EXACT key names from the template — do NOT invent new keys
- Copy numbers exactly — do NOT calculate or infer
- Set page_start/page_end for each invoice
- Return {{"invoices": [...]}}

TEMPLATE:
{template}

JSON:"""


def get_repair_prompt(invalid_json: str, error_message: str) -> str:
    """Build a repair prompt for invalid multi-invoice JSON."""
    template = get_multi_invoice_template()

    return f"""The following JSON has errors. Fix it to match the template EXACTLY.

ERROR: {error_message}

BROKEN JSON:
{invalid_json}

TEMPLATE:
{template}

FIX RULES:
- Return ONLY valid JSON — no markdown, no comments
- Use EXACTLY the key names in the template — do NOT rename or add keys
- registrations = [{{"type":"…","value":"…"}}] (objects, not strings)
- payment_details = ["…"] (strings)
- All numbers must be numeric, not strings
- Wrap result as {{"invoices": [...]}}

FIXED JSON:"""


# ═══════════════════════════════════════════════════════════════════════════
# JSON pre-processing — fix common LLM mistakes before Pydantic sees them
# ═══════════════════════════════════════════════════════════════════════════

# Wrong field names the LLM commonly invents → correct names
_FIELD_RENAMES: dict[str, str] = {
    # Line-item keys
    "item_number": "line_no", "item_no": "line_no", "line_number": "line_no",
    "sku": "product_code", "item_code": "product_code",
    "article_number": "product_code", "article_no": "product_code",
    "article": "product_code",
    "designation": "description", "item_description": "description",
    "item_name": "description", "product_name": "description",
    "qty": "quantity",
    "total": "line_total", "total_price": "line_total",
    "total_excl_tax": "line_total", "total_incl_tax": "line_total",
    "amount": "line_total",
    "unit_price_excl_tax": "unit_price", "unit_price_incl_tax": "unit_price",
    "price": "unit_price", "price_per_unit": "unit_price",
    "vat_rate": "tax_rate", "tax_percent": "tax_rate",
    "vat_amount": "tax_amount",
    "unit": "unit_measure", "uom": "unit_measure",
    # Tax entry keys
    "tax_code": "code", "vat_type": "code", "vat_code": "code",
    "tax_base": "base", "base_amount": "base",
    "amount_excl": "base", "amount_vat_excl": "base", "vat_excl": "base",
    "amount_incl": "amount", "amount_vat_incl": "amount", "vat_incl": "amount",
    # Registration keys
    "number": "value", "reg_number": "value",
    "registration_number": "value", "reg_type": "type",
    # Identifier keys
    "invoice_number": "document_number", "receipt_number": "document_number",
    "bill_number": "document_number", "order_number": "document_number",
    "reference_number": "document_number", "doc_number": "document_number",
    "ref": "document_number",
    # Party keys
    "company_name": "name", "vendor": "name", "seller": "name",
    "buyer": "name", "client": "name",
    "tel": "phone", "telephone": "phone",
    "mail": "email", "url": "website", "web": "website",
    # Date keys
    "date": "issue_date", "invoice_date": "issue_date",
    "receipt_date": "issue_date", "date_of_issue": "issue_date",
    # Totals keys
    "subtotal": "net_amount", "sub_total": "net_amount",
    "total_excl": "net_amount", "total_ht": "net_amount",
    "total_excl_vat": "net_amount",
    "vat_total": "tax_amount", "total_vat": "tax_amount",
    "total_tax": "tax_amount",
    "total_incl": "gross_amount", "total_ttc": "gross_amount",
    "total_incl_vat": "gross_amount", "grand_total": "gross_amount",
    "final_total": "gross_amount",
    "tip": "tip_amount", "gratuity": "tip_amount",
}

# Fields that must always be numeric scalars
_NUMERIC_FIELDS = frozenset({
    "quantity", "unit_price", "line_total", "tax_rate", "tax_amount",
    "net_amount", "gross_amount", "tip_amount",
    "rate", "base", "amount", "line_no",
})


def _rename_keys(obj: Any) -> Any:
    """Recursively rename known wrong keys to the correct schema names."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            new_key = _FIELD_RENAMES.get(k, k)
            # Avoid overwriting an already-correct key with a renamed duplicate
            if new_key in out and out[new_key] is not None:
                continue
            out[new_key] = _rename_keys(v)
        return out
    if isinstance(obj, list):
        return [_rename_keys(i) for i in obj]
    return obj


def _fix_registrations(obj: Any) -> Any:
    """Convert plain-string registrations into {type, value} objects."""
    if not isinstance(obj, dict):
        if isinstance(obj, list):
            for item in obj:
                _fix_registrations(item)
        return obj

    if "registrations" in obj:
        val = obj["registrations"]
        if isinstance(val, dict):
            # Object instead of array — unwrap
            inner = val.get("registration_details", list(val.values()))
            obj["registrations"] = inner if isinstance(inner, list) else []
            val = obj["registrations"]
        if isinstance(val, list):
            fixed: list[Any] = []
            for item in val:
                if isinstance(item, str):
                    rtype = "VAT" if any(t in item.upper() for t in ("VAT", "CHE", "TVA", "UST", "NIP")) else "registration"
                    fixed.append({"type": rtype, "value": item})
                elif isinstance(item, dict):
                    fixed.append(item)
            obj["registrations"] = fixed

    for v in obj.values():
        _fix_registrations(v)
    return obj


def _coerce_numbers(obj: Any) -> Any:
    """Convert string representations of numbers in numeric fields."""
    if not isinstance(obj, dict):
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    _coerce_numbers(item)
        return obj

    for key, val in obj.items():
        if key in _NUMERIC_FIELDS:
            if isinstance(val, list):
                # Array where scalar expected — take first number
                for item in val:
                    if isinstance(item, (int, float)):
                        obj[key] = item
                        break
                else:
                    obj[key] = None
            elif isinstance(val, str):
                cleaned = re.sub(r"[^\d.\-]", "", val.replace(",", "").replace("'", ""))
                if cleaned:
                    try:
                        obj[key] = int(cleaned) if key == "line_no" else float(cleaned)
                    except ValueError:
                        obj[key] = None
                else:
                    obj[key] = None
        elif isinstance(val, dict):
            _coerce_numbers(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _coerce_numbers(item)
    return obj


def _strip_markdown(text: str) -> str:
    """Remove markdown code fences, JS comments, trailing commas."""
    # Markdown fences
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if m:
        text = m.group(1).strip()
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

    # JS comments
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    # Trailing commas
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text.strip()


def preprocess_json(raw: str) -> str:
    """Clean raw LLM output into parseable JSON text."""
    return _strip_markdown(raw.strip())


def postprocess_data(data: dict) -> dict:
    """Fix common LLM data errors after parsing, before Pydantic validation."""
    data = _rename_keys(data)
    data = _fix_registrations(data)
    data = _coerce_numbers(data)
    return data


# ═══════════════════════════════════════════════════════════════════════════
# Main structuring class
# ═══════════════════════════════════════════════════════════════════════════


class JSONStructurer:
    """Structure extracted text into JSON using an LLM."""

    def __init__(self, model: str = STRUCTURING_MODEL):
        self.model = model

    # ── internal helpers ──────────────────────────────────────────────────

    def _extract_and_fix(self, response: str) -> Tuple[Optional[dict], str, Optional[str]]:
        """Parse LLM response → cleaned JSON text + postprocessed dict.

        Returns (data_dict | None, cleaned_json_text, error | None).
        """
        json_text = preprocess_json(response)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\n{json_text[:800]}")
            return None, json_text, f"Invalid JSON: {e}"

        if not isinstance(data, dict):
            return None, json_text, f"Expected object, got {type(data).__name__}"

        data = postprocess_data(data)
        return data, json_text, None

    def _validate_single(self, data: dict) -> Tuple[Optional[DocumentSchema], Optional[str]]:
        try:
            return DocumentSchema(**data), None
        except ValidationError as e:
            msgs = [f"{err['loc']}: {err['msg']}" for err in e.errors()[:5]]
            logger.error(f"Validation: {msgs}")
            return None, "; ".join(msgs)

    def _validate_multi(self, data: dict) -> Tuple[Optional[MultiInvoiceOutput], Optional[str]]:
        # Auto-wrap single invoice
        if "invoices" not in data and "document" in data:
            data = {"invoices": [data]}
        # Postprocess each invoice individually
        if "invoices" in data and isinstance(data["invoices"], list):
            data["invoices"] = [
                postprocess_data(inv) if isinstance(inv, dict) else inv
                for inv in data["invoices"]
            ]
        try:
            return MultiInvoiceOutput(**data), None
        except ValidationError as e:
            msgs = [f"{err['loc']}: {err['msg']}" for err in e.errors()[:5]]
            return None, "; ".join(msgs)

    # ── public API ────────────────────────────────────────────────────────

    async def structure_single_page(
        self,
        extracted_text: str,
        page_number: int,
        allow_repair: bool = True,
    ) -> Tuple[Optional[DocumentSchema], str, int, Optional[str]]:
        """Structure one page of text into JSON.

        Returns (model | None, raw_json, elapsed_ms, error | None).
        """
        logger.info(f"Structuring page {page_number}")
        t0 = time.time()

        try:
            # ── attempt 1 ────────────────────────────────────────────────
            prompt = get_single_page_prompt(extracted_text, page_number)
            resp = await structuring_client.structure_text(prompt)
            data, raw, parse_err = self._extract_and_fix(resp)

            if data is not None:
                model, val_err = self._validate_single(data)
                if model is not None:
                    model.page_start = page_number
                    model.page_end = page_number
                    ms = int((time.time() - t0) * 1000)
                    logger.info(f"Page {page_number} OK in {ms}ms")
                    return model, raw, ms, None
                error = val_err
            else:
                error = parse_err

            # ── attempt 2: repair ────────────────────────────────────────
            if allow_repair:
                logger.warning(f"Page {page_number} attempt-1 failed: {error}")
                repair_resp = await structuring_client.structure_text(
                    get_single_page_repair_prompt(raw, error, page_number)
                )
                data2, raw2, parse_err2 = self._extract_and_fix(repair_resp)

                if data2 is not None:
                    model2, val_err2 = self._validate_single(data2)
                    if model2 is not None:
                        model2.page_start = page_number
                        model2.page_end = page_number
                        ms = int((time.time() - t0) * 1000)
                        logger.info(f"Page {page_number} repaired in {ms}ms")
                        return model2, raw2, ms, None
                    error = val_err2
                else:
                    error = parse_err2

                ms = int((time.time() - t0) * 1000)
                return None, raw2 or raw, ms, f"Failed after repair: {error}"

            ms = int((time.time() - t0) * 1000)
            return None, raw, ms, error

        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            logger.error(f"Error on page {page_number}: {e}")
            return None, "", ms, str(e)

    async def structure_text(
        self,
        extracted_text: str,
        page_count: int = 1,
        allow_repair: bool = True,
    ) -> Tuple[Optional[List[DocumentSchema]], str, int, Optional[str]]:
        """Structure multi-page text into JSON (multiple invoices).

        Returns (invoices | None, raw_json, elapsed_ms, error | None).
        """
        logger.info(f"Structuring {page_count}-page document")
        t0 = time.time()

        try:
            prompt = get_structuring_prompt(extracted_text, page_count)
            resp = await structuring_client.structure_text(prompt)
            data, raw, parse_err = self._extract_and_fix(resp)

            if data is not None:
                model, val_err = self._validate_multi(data)
                if model is not None:
                    ms = int((time.time() - t0) * 1000)
                    logger.info(f"{len(model.invoices)} invoice(s) in {ms}ms")
                    return model.invoices, raw, ms, None
                error = val_err
            else:
                error = parse_err

            if allow_repair:
                logger.warning(f"Multi attempt-1 failed: {error}")
                repair_resp = await structuring_client.structure_text(
                    get_repair_prompt(raw, error)
                )
                data2, raw2, parse_err2 = self._extract_and_fix(repair_resp)

                if data2 is not None:
                    model2, val_err2 = self._validate_multi(data2)
                    if model2 is not None:
                        ms = int((time.time() - t0) * 1000)
                        logger.info(f"Repair OK: {len(model2.invoices)} invoice(s) in {ms}ms")
                        return model2.invoices, raw2, ms, None
                    error = val_err2
                else:
                    error = parse_err2

                ms = int((time.time() - t0) * 1000)
                return None, raw2 or raw, ms, f"Failed after repair: {error}"

            ms = int((time.time() - t0) * 1000)
            return None, raw, ms, error

        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            logger.error(f"Error during structuring: {e}")
            return None, "", ms, str(e)

    # ── file I/O helpers ──────────────────────────────────────────────────

    def save_page_json(self, invoice: DocumentSchema, document_id: str, page_number: int) -> Path:
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        p = JSON_DIR / f"{document_id}_page_{page_number}.json"
        p.write_text(json.dumps(invoice.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Saved page {page_number} → {p}")
        return p

    def save_invoice_json(self, invoice: DocumentSchema, document_id: str, invoice_index: int) -> Path:
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        p = JSON_DIR / f"{document_id}_invoice_{invoice_index}.json"
        p.write_text(json.dumps(invoice.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Saved invoice {invoice_index} → {p}")
        return p

    def save_all_invoices_json(self, invoices: List[DocumentSchema], document_id: str) -> Path:
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        p = JSON_DIR / f"{document_id}.json"
        d = {"invoices": [inv.model_dump() for inv in invoices]}
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Saved {len(invoices)} invoices → {p}")
        return p

    def save_json(self, model: DocumentSchema, document_id: str) -> Path:
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        p = JSON_DIR / f"{document_id}.json"
        p.write_text(json.dumps(model.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Saved JSON → {p}")
        return p

    def save_raw_json(self, raw_json: str, document_id: str, suffix: str = "_raw") -> Path:
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        p = JSON_DIR / f"{document_id}{suffix}.json"
        p.write_text(raw_json, encoding="utf-8")
        return p


# Global instance
json_structurer = JSONStructurer()
