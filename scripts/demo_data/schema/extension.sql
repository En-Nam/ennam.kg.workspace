-- pharmacy_demo extension for Proactive Intelligence P0 (Plan A).
-- Only ADDs tables/columns: existing table and column names are a contract for packs/_projects mapping.
-- Applied after base.sql and BEFORE loading CSVs (load order in load_pharmacy_demo.sh respects the FKs).

ALTER TABLE public.employees ADD COLUMN hourly_wage numeric;
ALTER TABLE public.prescriptions ADD COLUMN acquisition_cost numeric;

CREATE TABLE public.vendors (
    vendor_id text PRIMARY KEY,
    vendor_name text NOT NULL,
    lead_time_days integer NOT NULL CHECK (lead_time_days > 0),
    order_weekday integer NOT NULL CHECK (order_weekday BETWEEN 0 AND 6),
    payment_terms text,
    status text
);

CREATE TABLE public.product_costs (
    product_cost_id text PRIMARY KEY,
    product_id text NOT NULL REFERENCES public.products(product_id),
    store_id text REFERENCES public.stores(store_id),          -- NULL = chain-wide price list
    vendor_id text REFERENCES public.vendors(vendor_id),
    effective_from date NOT NULL,
    effective_to date,                                           -- NULL = still effective
    unit_cost numeric NOT NULL,
    change_reason text
);
CREATE INDEX product_costs_lookup ON public.product_costs (product_id, store_id, effective_from);

CREATE TABLE public.purchase_orders (
    po_id text PRIMARY KEY,
    store_id text NOT NULL REFERENCES public.stores(store_id),
    vendor_id text NOT NULL REFERENCES public.vendors(vendor_id),
    order_date date NOT NULL,
    expected_date date NOT NULL,
    received_datetime timestamp without time zone,
    status text NOT NULL
);

CREATE TABLE public.purchase_order_lines (
    po_line_id text PRIMARY KEY,
    po_id text NOT NULL REFERENCES public.purchase_orders(po_id),
    product_id text NOT NULL REFERENCES public.products(product_id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_cost numeric NOT NULL
);

ALTER TABLE public.products
    ADD CONSTRAINT fk_products_vendor FOREIGN KEY (vendor_id) REFERENCES public.vendors(vendor_id);

COMMENT ON COLUMN public.employees.hourly_wage IS 'Hourly wage in USD (labor cost = shift hours x wage)';
COMMENT ON COLUMN public.prescriptions.acquisition_cost IS 'Acquisition cost of the dispensed quantity at fill date and store (USD)';
COMMENT ON TABLE public.product_costs IS 'Dated unit cost history; store_id NULL = chain price list, non-NULL = store-specific override';
COMMENT ON COLUMN public.inventory_movements.movement_type IS 'SALE | REFUND_RETURN | RECEIPT (vendor delivery, reference_id = purchase_orders.po_id)';
