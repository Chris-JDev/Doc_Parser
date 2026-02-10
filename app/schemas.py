"""Pydantic schemas for the structured JSON output.

This module defines the schema for the output JSON.
All keys must be present, even if values are null or empty lists.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class LenientBaseModel(BaseModel):
    """Base model that ignores extra fields from LLM output."""
    class Config:
        extra = "ignore"


class Source(LenientBaseModel):
    """Source location information for extracted fields."""
    page_id: Optional[int] = None
    polygon: List[Any] = Field(default_factory=list)


class Locale(LenientBaseModel):
    """Locale information for the document."""
    language: Optional[str] = None
    currency: Optional[str] = None
    country: Optional[str] = None


class Identifiers(LenientBaseModel):
    """Document identifiers."""
    document_number: Optional[str] = None  # Invoice/Receipt/Bill/Order/PO/Reference number
    reference_numbers: List[str] = Field(default_factory=list)  # Additional references


class Dates(LenientBaseModel):
    """Document dates."""
    issue_date: Optional[str] = None  # ISO 8601
    due_date: Optional[str] = None
    payment_date: Optional[str] = None
    time: Optional[str] = None


class Status(LenientBaseModel):
    """Document status information."""
    payment_status: Optional[str] = None


class DocumentInfo(LenientBaseModel):
    """Main document information section."""
    type: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    locale: Locale = Field(default_factory=Locale)
    identifiers: Identifiers = Field(default_factory=Identifiers)
    dates: Dates = Field(default_factory=Dates)
    status: Status = Field(default_factory=Status)


class Registration(LenientBaseModel):
    """Registration entry for supplier."""
    type: Optional[str] = None
    value: Optional[str] = None


class Supplier(LenientBaseModel):
    """Supplier information."""
    name: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    registrations: List[Registration] = Field(default_factory=list)
    payment_details: List[str] = Field(default_factory=list)


class Customer(LenientBaseModel):
    """Customer information."""
    name: Optional[str] = None
    customer_id: Optional[str] = None
    address: Optional[str] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    company_registrations: List[str] = Field(default_factory=list)


class Parties(LenientBaseModel):
    """Parties involved in the document."""
    supplier: Supplier = Field(default_factory=Supplier)
    customer: Customer = Field(default_factory=Customer)


class LineItem(LenientBaseModel):
    """Line item entry."""
    line_no: Optional[int] = None
    product_code: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_measure: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_amount: Optional[float] = None
    confidence: Optional[float] = None
    source: Source = Field(default_factory=Source)


class Totals(LenientBaseModel):
    """Document totals."""
    net_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    gross_amount: Optional[float] = None
    tip_amount: Optional[float] = None


class TaxEntry(LenientBaseModel):
    """Tax entry."""
    code: Optional[str] = None
    rate: Optional[float] = None
    base: Optional[float] = None
    amount: Optional[float] = None
    confidence: Optional[float] = None
    source: Source = Field(default_factory=Source)


class FieldMetadata(LenientBaseModel):
    """Metadata for an extracted field."""
    value: Optional[Any] = None
    confidence: Optional[float] = None
    source: Source = Field(default_factory=Source)


class ExtractionMetadata(LenientBaseModel):
    """Extraction metadata container."""
    fields: Dict[str, FieldMetadata] = Field(default_factory=dict)


class DocumentSchema(LenientBaseModel):
    """The complete document schema."""
    document: DocumentInfo = Field(default_factory=DocumentInfo)
    parties: Parties = Field(default_factory=Parties)
    line_items: List[LineItem] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    taxes: List[TaxEntry] = Field(default_factory=list)
    extraction_metadata: ExtractionMetadata = Field(default_factory=ExtractionMetadata)
    # Page range for multi-invoice documents
    page_start: Optional[int] = None
    page_end: Optional[int] = None


class MultiInvoiceOutput(LenientBaseModel):
    """Output schema for multiple invoices in one document."""
    invoices: List[DocumentSchema] = Field(default_factory=list)


def get_json_template() -> str:
    """Return the JSON template as a string for prompting."""
    return '''{
  "document": {
    "type": null,
    "category": null,
    "subcategory": null,
    "locale": {
      "language": null,
      "currency": null,
      "country": null
    },
    "identifiers": {
      "document_number": null,
      "reference_numbers": []
    },
    "dates": {
      "issue_date": null,
      "due_date": null,
      "payment_date": null,
      "time": null
    },
    "status": {
      "payment_status": null
    }
  },
  "parties": {
    "supplier": {
      "name": null,
      "address": null,
      "email": null,
      "phone": null,
      "website": null,
      "registrations": [],
      "payment_details": []
    },
    "customer": {
      "name": null,
      "customer_id": null,
      "address": null,
      "billing_address": null,
      "shipping_address": null,
      "company_registrations": []
    }
  },
  "line_items": [],
  "totals": {
    "net_amount": null,
    "tax_amount": null,
    "gross_amount": null,
    "tip_amount": null
  },
  "taxes": [],
  "extraction_metadata": {
    "fields": {}
  },
  "page_start": null,
  "page_end": null
}'''


def get_multi_invoice_template() -> str:
    """Return the template for multiple invoices."""
    single_template = get_json_template()
    return f'''{{"invoices": [{single_template}]}}'''


def get_empty_schema() -> DocumentSchema:
    """Return an empty document schema with all default values."""
    return DocumentSchema()
