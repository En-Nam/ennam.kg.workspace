--
-- PostgreSQL database dump
--

\restrict bqd0eb6Ya2QmtqrYrAFez7JCRleXQVua0IaFVYrve5VlYcP8u4HzKMyHOC3aYkq

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events (
    audit_event_id text NOT NULL,
    event_datetime timestamp without time zone,
    store_id text,
    employee_id text,
    event_type text,
    entity_type text,
    entity_id text,
    action text,
    previous_value text,
    new_value text,
    approval_employee_id text,
    device_id text,
    success boolean
);


--
-- Name: cash_drawers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_drawers (
    drawer_session_id text NOT NULL,
    store_id text,
    register_id text,
    employee_id text,
    opened_at timestamp without time zone,
    closed_at timestamp without time zone,
    opening_cash numeric(12,2),
    expected_cash numeric(12,2),
    counted_cash numeric(12,2),
    cash_variance numeric(12,2),
    no_sale_open_count integer,
    cash_refund_total numeric(12,2),
    cash_sales_total numeric(12,2),
    approving_manager_id text,
    flagged boolean,
    flag_reason text
);


--
-- Name: customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customers (
    customer_id text NOT NULL,
    loyalty_id text,
    first_name text,
    last_name text,
    city text,
    state text,
    signup_date date,
    loyalty_tier text,
    preferred_store_id text
);


--
-- Name: discount_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discount_overrides (
    override_id text NOT NULL,
    transaction_id text,
    store_id text,
    employee_id text,
    approving_manager_id text,
    product_id text,
    override_datetime timestamp without time zone,
    original_amount numeric(12,2),
    adjusted_amount numeric(12,2),
    discount_amount numeric(12,2),
    discount_percent numeric(6,2),
    override_reason text,
    approval_method text,
    flagged boolean,
    flag_reason text
);


--
-- Name: employee_shifts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employee_shifts (
    shift_id text NOT NULL,
    employee_id text,
    store_id text,
    scheduled_start timestamp without time zone,
    scheduled_end timestamp without time zone,
    actual_clock_in timestamp without time zone,
    actual_clock_out timestamp without time zone,
    regular_hours numeric(5,2),
    overtime_hours numeric(5,2),
    late_minutes integer,
    early_departure_minutes integer,
    role_during_shift text,
    manager_on_duty text
);


--
-- Name: employees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employees (
    employee_id text NOT NULL,
    first_name text,
    last_name text,
    store_id text,
    role text,
    department text,
    hire_date date,
    status text,
    refund_permission boolean,
    void_permission boolean,
    discount_override_permission boolean,
    pharmacy_access boolean
);


--
-- Name: insurance_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insurance_claims (
    claim_id text NOT NULL,
    prescription_id text,
    store_id text,
    payer_name text,
    submitted_datetime timestamp without time zone,
    claim_amount numeric(10,2),
    approved_amount numeric(10,2),
    customer_amount numeric(10,2),
    claim_status text,
    rejection_code text,
    resubmission_count integer,
    resolved_datetime timestamp without time zone
);


--
-- Name: inventory_adjustments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_adjustments (
    adjustment_id text NOT NULL,
    store_id text,
    product_id text,
    employee_id text,
    approving_manager_id text,
    adjustment_datetime timestamp without time zone,
    adjustment_type text,
    quantity_before integer,
    adjustment_quantity integer,
    quantity_after integer,
    adjustment_value numeric(12,2),
    reason text,
    reference_document text,
    flagged boolean,
    flag_reason text
);


--
-- Name: inventory_movements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_movements (
    movement_id text NOT NULL,
    store_id text,
    product_id text,
    movement_datetime timestamp without time zone,
    movement_type text,
    quantity_change integer,
    reference_id text,
    employee_id text
);


--
-- Name: inventory_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory_snapshots (
    snapshot_id text NOT NULL,
    snapshot_date date,
    store_id text,
    product_id text,
    system_quantity integer,
    counted_quantity integer,
    variance_quantity integer,
    variance_value numeric(12,2),
    expired_quantity integer,
    status text
);


--
-- Name: invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoices (
    invoice_id text NOT NULL,
    invoice_number text,
    transaction_id text,
    store_id text,
    customer_id text,
    billing_type text,
    billing_name text,
    tax_id text,
    payment_terms text,
    issued_datetime timestamp without time zone,
    due_date date,
    subtotal numeric(12,2),
    tax_amount numeric(12,2),
    total_amount numeric(12,2),
    status text,
    paid_date date
);


--
-- Name: payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments (
    payment_id text NOT NULL,
    transaction_id text,
    payment_method text,
    amount numeric(12,2),
    payment_datetime timestamp without time zone,
    status text
);


--
-- Name: prescriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prescriptions (
    prescription_id text NOT NULL,
    prescription_number text,
    store_id text,
    pharmacist_employee_id text,
    technician_employee_id text,
    customer_id text,
    product_id text,
    received_datetime timestamp without time zone,
    filled_datetime timestamp without time zone,
    picked_up_datetime timestamp without time zone,
    quantity integer,
    refill_number integer,
    cash_price numeric(10,2),
    customer_payment numeric(10,2),
    insurance_payment numeric(10,2),
    status text,
    turnaround_minutes integer,
    reversal_flag boolean,
    exception_reason text
);


--
-- Name: products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.products (
    product_id text NOT NULL,
    sku text,
    upc text,
    product_name text NOT NULL,
    category text,
    subcategory text,
    brand text,
    prescription_required boolean,
    controlled_category text,
    unit_cost numeric(10,2),
    retail_price numeric(10,2),
    gross_margin_percent numeric(6,2),
    reorder_point integer,
    vendor_id text,
    status text
);


--
-- Name: receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.receipts (
    receipt_id text NOT NULL,
    transaction_id text,
    receipt_number text,
    print_type text,
    printed_datetime timestamp without time zone,
    printed_by_employee_id text,
    register_id text,
    store_id text,
    print_reason text
);


--
-- Name: refund_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refund_items (
    refund_item_id text NOT NULL,
    refund_id text,
    product_id text,
    quantity integer,
    original_unit_price numeric(10,2),
    refunded_amount numeric(12,2),
    returned_to_inventory boolean,
    item_condition text,
    disposal_required boolean
);


--
-- Name: refunds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refunds (
    refund_id text NOT NULL,
    refund_transaction_id text,
    original_transaction_id text,
    store_id text,
    register_id text,
    employee_id text,
    approving_manager_id text,
    customer_id text,
    refund_datetime timestamp without time zone,
    refund_amount numeric(12,2),
    refund_method text,
    refund_reason text,
    original_receipt_present boolean,
    days_after_purchase integer,
    manager_override boolean,
    risk_score integer,
    flagged boolean,
    flag_reason text
);


--
-- Name: stores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stores (
    store_id text NOT NULL,
    store_name text NOT NULL,
    city text,
    state text,
    manager_name text,
    opening_date date,
    pharmacy_enabled boolean,
    front_store_enabled boolean,
    status text
);


--
-- Name: transaction_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transaction_items (
    transaction_item_id text NOT NULL,
    transaction_id text,
    product_id text,
    quantity integer,
    unit_price numeric(10,2),
    unit_cost numeric(10,2),
    discount_amount numeric(10,2),
    tax_amount numeric(10,2),
    line_total numeric(12,2),
    override_applied boolean,
    override_employee_id text,
    department text
);


--
-- Name: transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transactions (
    transaction_id text NOT NULL,
    receipt_number text,
    store_id text,
    register_id text,
    employee_id text,
    customer_id text,
    transaction_datetime timestamp without time zone,
    transaction_type text,
    subtotal numeric(12,2),
    discount_amount numeric(12,2),
    tax_amount numeric(12,2),
    total_amount numeric(12,2),
    payment_method text,
    item_count integer,
    prescription_included boolean,
    loyalty_used boolean,
    manager_override boolean,
    status text
);


--
-- Name: voids; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.voids (
    void_id text NOT NULL,
    transaction_id text,
    store_id text,
    register_id text,
    employee_id text,
    approving_manager_id text,
    void_datetime timestamp without time zone,
    void_amount numeric(12,2),
    void_reason text,
    stage text,
    flagged boolean,
    flag_reason text
);


--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (audit_event_id);


--
-- Name: cash_drawers cash_drawers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_drawers
    ADD CONSTRAINT cash_drawers_pkey PRIMARY KEY (drawer_session_id);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (customer_id);


--
-- Name: discount_overrides discount_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discount_overrides
    ADD CONSTRAINT discount_overrides_pkey PRIMARY KEY (override_id);


--
-- Name: employee_shifts employee_shifts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_shifts
    ADD CONSTRAINT employee_shifts_pkey PRIMARY KEY (shift_id);


--
-- Name: employees employees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_pkey PRIMARY KEY (employee_id);


--
-- Name: insurance_claims insurance_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insurance_claims
    ADD CONSTRAINT insurance_claims_pkey PRIMARY KEY (claim_id);


--
-- Name: inventory_adjustments inventory_adjustments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_adjustments
    ADD CONSTRAINT inventory_adjustments_pkey PRIMARY KEY (adjustment_id);


--
-- Name: inventory_movements inventory_movements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT inventory_movements_pkey PRIMARY KEY (movement_id);


--
-- Name: inventory_snapshots inventory_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_snapshots
    ADD CONSTRAINT inventory_snapshots_pkey PRIMARY KEY (snapshot_id);


--
-- Name: invoices invoices_invoice_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_invoice_number_key UNIQUE (invoice_number);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (invoice_id);


--
-- Name: invoices invoices_transaction_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_transaction_id_key UNIQUE (transaction_id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (payment_id);


--
-- Name: prescriptions prescriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescriptions
    ADD CONSTRAINT prescriptions_pkey PRIMARY KEY (prescription_id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (product_id);


--
-- Name: receipts receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.receipts
    ADD CONSTRAINT receipts_pkey PRIMARY KEY (receipt_id);


--
-- Name: refund_items refund_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refund_items
    ADD CONSTRAINT refund_items_pkey PRIMARY KEY (refund_item_id);


--
-- Name: refunds refunds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refunds
    ADD CONSTRAINT refunds_pkey PRIMARY KEY (refund_id);


--
-- Name: stores stores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_pkey PRIMARY KEY (store_id);


--
-- Name: transaction_items transaction_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_items
    ADD CONSTRAINT transaction_items_pkey PRIMARY KEY (transaction_item_id);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (transaction_id);


--
-- Name: voids voids_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voids
    ADD CONSTRAINT voids_pkey PRIMARY KEY (void_id);


--
-- Name: inventory_adjustments fk_adj_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_adjustments
    ADD CONSTRAINT fk_adj_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: inventory_adjustments fk_adj_product; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_adjustments
    ADD CONSTRAINT fk_adj_product FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: inventory_adjustments fk_adj_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_adjustments
    ADD CONSTRAINT fk_adj_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: audit_events fk_audit_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT fk_audit_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: audit_events fk_audit_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT fk_audit_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: insurance_claims fk_claim_rx; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insurance_claims
    ADD CONSTRAINT fk_claim_rx FOREIGN KEY (prescription_id) REFERENCES public.prescriptions(prescription_id);


--
-- Name: insurance_claims fk_claim_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insurance_claims
    ADD CONSTRAINT fk_claim_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: customers fk_customers_pref_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT fk_customers_pref_store FOREIGN KEY (preferred_store_id) REFERENCES public.stores(store_id);


--
-- Name: cash_drawers fk_drawer_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_drawers
    ADD CONSTRAINT fk_drawer_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: cash_drawers fk_drawer_manager; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_drawers
    ADD CONSTRAINT fk_drawer_manager FOREIGN KEY (approving_manager_id) REFERENCES public.employees(employee_id);


--
-- Name: cash_drawers fk_drawer_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_drawers
    ADD CONSTRAINT fk_drawer_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: employees fk_employees_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT fk_employees_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: invoices fk_invoice_customer; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT fk_invoice_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id);


--
-- Name: invoices fk_invoice_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT fk_invoice_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: invoices fk_invoice_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT fk_invoice_txn FOREIGN KEY (transaction_id) REFERENCES public.transactions(transaction_id);


--
-- Name: inventory_movements fk_mov_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT fk_mov_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: inventory_movements fk_mov_product; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT fk_mov_product FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: inventory_movements fk_mov_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_movements
    ADD CONSTRAINT fk_mov_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: discount_overrides fk_ovr_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discount_overrides
    ADD CONSTRAINT fk_ovr_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: discount_overrides fk_ovr_manager; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discount_overrides
    ADD CONSTRAINT fk_ovr_manager FOREIGN KEY (approving_manager_id) REFERENCES public.employees(employee_id);


--
-- Name: discount_overrides fk_ovr_product; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discount_overrides
    ADD CONSTRAINT fk_ovr_product FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: discount_overrides fk_ovr_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discount_overrides
    ADD CONSTRAINT fk_ovr_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: discount_overrides fk_ovr_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discount_overrides
    ADD CONSTRAINT fk_ovr_txn FOREIGN KEY (transaction_id) REFERENCES public.transactions(transaction_id);


--
-- Name: payments fk_payment_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT fk_payment_txn FOREIGN KEY (transaction_id) REFERENCES public.transactions(transaction_id);


--
-- Name: receipts fk_receipt_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.receipts
    ADD CONSTRAINT fk_receipt_employee FOREIGN KEY (printed_by_employee_id) REFERENCES public.employees(employee_id);


--
-- Name: receipts fk_receipt_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.receipts
    ADD CONSTRAINT fk_receipt_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: receipts fk_receipt_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.receipts
    ADD CONSTRAINT fk_receipt_txn FOREIGN KEY (transaction_id) REFERENCES public.transactions(transaction_id);


--
-- Name: refunds fk_refund_customer; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refunds
    ADD CONSTRAINT fk_refund_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id);


--
-- Name: refunds fk_refund_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refunds
    ADD CONSTRAINT fk_refund_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: refunds fk_refund_manager; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refunds
    ADD CONSTRAINT fk_refund_manager FOREIGN KEY (approving_manager_id) REFERENCES public.employees(employee_id);


--
-- Name: refunds fk_refund_orig_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refunds
    ADD CONSTRAINT fk_refund_orig_txn FOREIGN KEY (original_transaction_id) REFERENCES public.transactions(transaction_id);


--
-- Name: refunds fk_refund_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refunds
    ADD CONSTRAINT fk_refund_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: refund_items fk_refunditem_product; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refund_items
    ADD CONSTRAINT fk_refunditem_product FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: refund_items fk_refunditem_refund; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refund_items
    ADD CONSTRAINT fk_refunditem_refund FOREIGN KEY (refund_id) REFERENCES public.refunds(refund_id);


--
-- Name: prescriptions fk_rx_customer; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescriptions
    ADD CONSTRAINT fk_rx_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id);


--
-- Name: prescriptions fk_rx_pharmacist; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescriptions
    ADD CONSTRAINT fk_rx_pharmacist FOREIGN KEY (pharmacist_employee_id) REFERENCES public.employees(employee_id);


--
-- Name: prescriptions fk_rx_product; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescriptions
    ADD CONSTRAINT fk_rx_product FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: prescriptions fk_rx_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescriptions
    ADD CONSTRAINT fk_rx_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: prescriptions fk_rx_technician; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prescriptions
    ADD CONSTRAINT fk_rx_technician FOREIGN KEY (technician_employee_id) REFERENCES public.employees(employee_id);


--
-- Name: employee_shifts fk_shift_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_shifts
    ADD CONSTRAINT fk_shift_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: employee_shifts fk_shift_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_shifts
    ADD CONSTRAINT fk_shift_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: inventory_snapshots fk_snap_product; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_snapshots
    ADD CONSTRAINT fk_snap_product FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: inventory_snapshots fk_snap_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory_snapshots
    ADD CONSTRAINT fk_snap_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: transactions fk_txn_customer; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT fk_txn_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id);


--
-- Name: transactions fk_txn_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT fk_txn_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: transactions fk_txn_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT fk_txn_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: transaction_items fk_txnitem_product; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_items
    ADD CONSTRAINT fk_txnitem_product FOREIGN KEY (product_id) REFERENCES public.products(product_id);


--
-- Name: transaction_items fk_txnitem_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_items
    ADD CONSTRAINT fk_txnitem_txn FOREIGN KEY (transaction_id) REFERENCES public.transactions(transaction_id);


--
-- Name: voids fk_void_employee; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voids
    ADD CONSTRAINT fk_void_employee FOREIGN KEY (employee_id) REFERENCES public.employees(employee_id);


--
-- Name: voids fk_void_store; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voids
    ADD CONSTRAINT fk_void_store FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- Name: voids fk_void_txn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voids
    ADD CONSTRAINT fk_void_txn FOREIGN KEY (transaction_id) REFERENCES public.transactions(transaction_id);


--
-- PostgreSQL database dump complete
--

\unrestrict bqd0eb6Ya2QmtqrYrAFez7JCRleXQVua0IaFVYrve5VlYcP8u4HzKMyHOC3aYkq

