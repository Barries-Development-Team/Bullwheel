# Description Templates (New Product)

**New Product**'s `description` field can be auto-generated from its other fields, driven by a
**Description Template** chosen on the `description_template` Link field. This mirrors the
`Zebra Printer Label` pattern (see `LABEL_PRINTING.md`): the template is **data**, not code — a
Jinja string stored on a DocType record — so creating or editing a template is a Desk task, not
a deployment. No `bench restart` or `migrate` is needed to add, edit, or remove a template.

## Files

| File | Role |
|---|---|
| `ascend/doctype/description_template/description_template.py` | `DescriptionTemplate.render(product)` — renders the stored `template` (Jinja) with `product` bound to `doc`, then collapses all whitespace (including newlines from multi-line templates) onto a single line. |
| `ascend/doctype/description_template/description_template.json` | `Description Template` DocType: `template_name` (autoname, unique) + `template` (Code field, Jinja syntax highlighting). |
| `ascend/doctype/new_product/new_product.py` | `generate_description(template_name, product)` — whitelisted preview endpoint. `NewProduct.validate()` — authoritative re-render on every save. |
| `ascend/doctype/new_product/new_product.js` | Client-side real-time preview: calls `generate_description` whenever `description_template` or a field in `DESCRIPTION_SOURCE_FIELDS` changes, and writes the result into `description`. |

## How it's wired up

- **While editing:** changing `description_template`, or any field listed in `DESCRIPTION_SOURCE_FIELDS` at the top of `new_product.js`, calls the whitelisted `generate_description` method with the form's current (unsaved) values and writes the result into `description`. This is a `frappe.call` to a static method rather than `frm.call`, per this app's performance convention — no document instantiation on the server for what fires on every relevant field blur.
- **`description` becomes read-only** whenever `description_template` is set (`read_only_depends_on` on the field) — it signals the value is managed by the template. Clear `description_template` to edit `description` by hand again.
- **On save**, `NewProduct.validate()` re-renders `description` from the current template unconditionally — this is the authoritative pass. It runs whether the document was created via the form, the Bulk Product Import, or the API, and it always wins over whatever the client last previewed, so a template edited *after* the client's last preview still takes effect.
- If `description_template` is blank, none of this runs — `description` is a plain, manually-entered field as before.

## Creating a template

1. Go to **Description Template** in the Desk (New).
2. Set **Template Name** — this is the value that will appear in New Product's Description
   Template dropdown.
3. Write the **Template** field as a Jinja template. The New Product being edited is available
   as `doc`; every New Product field is readable as `doc.<fieldname>` (see field list below).
4. Save. It's immediately selectable on New Product — no restart or migrate needed.

Multi-line templates are fine and often more readable — the renderer collapses all
whitespace (including newlines) down to single spaces in the final `description`, so
indentation and line breaks in the template are free.

### Available fields (`doc.<fieldname>`)

| Fieldname | Meaning |
|---|---|
| `vpn` | Vendor Part Number |
| `brand` | Brand |
| `category` | Product Category (Link) |
| `style_name` | Style / Model Name |
| `style_number` | Style Number |
| `manufacturers_part_number` | Manufacturer Part Number (MPN) |
| `color` | Color |
| `size` | Size |
| `gender` | Gender |
| `season` | Season |
| `year` | Year |
| `upc` | UPC / custom barcode |
| `price` | MSRP |
| `estimated_cost` | Cost |
| `case` | Whether this is a case (checkbox, `0`/`1`) |
| `case_quantity`, `case_upc`, `case_msrp` | Case Quantity / Case UPC / Case MSRP — only meaningful when `case` is set |

Any other New Product field (e.g. `store_sku`) is technically reachable too, but the fields
above are the ones intended for descriptions.

### Optional fields: guard against `None`

Frappe's `frappe._dict` returns `None` for a field that isn't set, and Jinja renders `None`
as the literal text `"None"` — it will **not** silently disappear. Never interpolate an
optional field directly:

```jinja
{{ doc.color }}                         {# WRONG: prints "None" when color is blank #}
```

Use the `default` filter with `true` as the second argument (treats `None`, not just
"undefined", as needing the default) for a plain substitution:

```jinja
{{ doc.color | default('', true) }}    {# prints "" when color is blank #}
```

Use an `{% if %}` block when the field needs its own label, separator, or punctuation that
should also disappear when the field is blank:

```jinja
{% if doc.color %}, {{ doc.color }}{% endif %}
```

`vpn`, `brand`, `price`, and `estimated_cost` are required on every New Product, so they never
need this guard. Every other field does.

### Example templates

**Apparel** — `"{{ doc.brand }} {{ doc.style_name }}{% if doc.color %} - {{ doc.color }}{% endif %}{% if doc.size %}, {{ doc.size }}{% endif %}"`
→ `Patagonia Down Sweater - Black, M`

**Skis (with case handling)**:

```jinja
{{ doc.brand }} {{ doc.style_name }}
{%- if doc.size %} {{ doc.size }}cm{% endif %}
{%- if doc.year %} ({{ doc.year }}){% endif %}
{%- if doc.case %} - Case of {{ doc.case_quantity }}{% endif %}
```

→ `Rossignol Experience 88 170cm (2026) - Case of 4`

## Wiring a new field into the live preview

`new_product.js` triggers a live preview from an explicit `DESCRIPTION_SOURCE_FIELDS` list
(deliberate, not derived automatically — matches this app's existing style of explicit
field lists over implicit "any field" hooks). If you write a template that reads a New
Product field **not already in that list**, live-as-you-type preview won't pick it up —
add the fieldname to `DESCRIPTION_SOURCE_FIELDS`. This is a convenience only: even without
it, `validate()` always re-renders `description` correctly on save.
