# Custom lead layouts

In Leads, select **Customize columns**. Rename columns, move them up/down, hide them,
choose stored data sources, and add custom fields. Custom keys are stable storage keys;
rename the column label to change its presentation without changing its stored values.
Settings are shared within the active workspace and saved on the server. Concurrent
layout saves are rejected with a reload message to prevent silent overwrites.

**Upload sample format** accepts UTF-8 CSV or Excel .xlsx, up to 2 MB and 64 columns.
The first nonempty row of the first worksheet supplies column headers. Sample rows
are not imported as contacts. Older .xls files must first be saved as .xlsx. Review
suggested source matches, select types and formats, and save the layout. Unsupported
or duplicate headers are reported rather than silently overwritten.

Use **Edit details** on a lead to fill contact and custom fields. Number, date and
boolean fields are validated. Required custom fields apply to manual edits; they do
not prevent the existing conversation capture pipeline from creating an incomplete
lead. Removing a column does not delete stored lead data. Adding a field does not
invent values or automatically extract new information from historical conversations.
Website attribution fields captured by the widget can be selected as data sources.

**Export CSV** and **Export Excel** include all matching leads across pages, up to
10,000 records, in the saved column order and formats. Narrow filters for larger
exports. Formula-like CSV values are escaped; Excel strings are written as text,
not executable formulas. Phone numbers retain their leading + and zeroes in Excel.
The export file contains lead data only, without CRM action buttons.

To route fields to a CRM, choose a connection in the layout editor and assign its
API field names to columns. Discovered writable fields are suggested. **Save & apply
CRM mapping** replaces field rules, retains existing constants, and validates before
activation. Fields with blank destinations are omitted from those rules. Providers
may add required defaults. Agent name is a display-only source and cannot be mapped.
The existing connection, routing, authorization and delivery/retry checks still apply.
This configures payloads for supported connectors; it does not create custom fields
inside a provider. Create those fields in the CRM first, then refresh its schema.
