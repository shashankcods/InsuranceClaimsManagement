-- =====================================================================
-- 01_schema.sql  --  Insurance & Claims Management System (MySQL 8, InnoDB)
-- 15 tables in BCNF. Run inside the target database (see run_all.sql).
-- =====================================================================

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS claim_status_log, claim_payout, claim_assessment, claim_document,
                     claim, premium_payment, nominee, policy, adjuster, provider,
                     policy_type, customer, agent, pincode, fraud_model;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- pincode: removes the transitive dependency pincode -> city, state that
-- customer and provider would otherwise carry (BCNF).
-- ---------------------------------------------------------------------
CREATE TABLE pincode (
    pincode  CHAR(6)     NOT NULL PRIMARY KEY,
    city     VARCHAR(60) NOT NULL,
    state    VARCHAR(60) NOT NULL,
    CONSTRAINT ck_pincode_format CHECK (pincode REGEXP '^[0-9]{6}$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- agent: sells policies; manager_id is a self-referencing FK (hierarchy)
-- ---------------------------------------------------------------------
CREATE TABLE agent (
    agent_id        INT AUTO_INCREMENT PRIMARY KEY,
    first_name      VARCHAR(50)  NOT NULL,
    last_name       VARCHAR(50)  NOT NULL,
    email           VARCHAR(120) NOT NULL,
    phone           VARCHAR(15)  NOT NULL,
    branch_city     VARCHAR(60)  NOT NULL,
    hire_date       DATE         NOT NULL,
    commission_rate DECIMAL(5,2) NOT NULL DEFAULT 5.00,
    manager_id      INT          NULL,
    CONSTRAINT uq_agent_email      UNIQUE (email),
    CONSTRAINT ck_agent_commission CHECK (commission_rate BETWEEN 0 AND 30),
    CONSTRAINT fk_agent_manager    FOREIGN KEY (manager_id) REFERENCES agent(agent_id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- customer: policy holder. City and state are reached through pincode.
-- ---------------------------------------------------------------------
CREATE TABLE customer (
    customer_id   INT AUTO_INCREMENT PRIMARY KEY,
    first_name    VARCHAR(50)  NOT NULL,
    last_name     VARCHAR(50)  NOT NULL,
    dob           DATE         NOT NULL,
    gender        CHAR(1)      NOT NULL,
    email         VARCHAR(120) NOT NULL,
    phone         VARCHAR(15)  NOT NULL,
    address_line  VARCHAR(200) NOT NULL,
    pincode       CHAR(6)      NOT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_customer_email   UNIQUE (email),
    CONSTRAINT ck_customer_gender  CHECK (gender IN ('M','F','O')),
    CONSTRAINT fk_customer_pincode FOREIGN KEY (pincode) REFERENCES pincode(pincode)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- policy_type: the product catalogue
-- ---------------------------------------------------------------------
CREATE TABLE policy_type (
    type_id          INT AUTO_INCREMENT PRIMARY KEY,
    type_name        VARCHAR(30)   NOT NULL,
    description      VARCHAR(255)  NULL,
    min_sum_assured  DECIMAL(12,2) NOT NULL,
    max_sum_assured  DECIMAL(12,2) NOT NULL,
    base_rate_pct    DECIMAL(5,3)  NOT NULL,   -- annual premium as % of sum assured
    max_term_years   INT           NOT NULL DEFAULT 1,
    CONSTRAINT uq_policy_type_name UNIQUE (type_name),
    CONSTRAINT ck_pt_sum_range     CHECK (min_sum_assured > 0 AND max_sum_assured >= min_sum_assured),
    CONSTRAINT ck_pt_rate          CHECK (base_rate_pct > 0 AND base_rate_pct <= 20),
    CONSTRAINT ck_pt_term          CHECK (max_term_years BETWEEN 1 AND 40)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- provider: hospitals / garages where claims are serviced
-- ---------------------------------------------------------------------
CREATE TABLE provider (
    provider_id   INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(120) NOT NULL,
    provider_type VARCHAR(20)  NOT NULL,
    pincode       CHAR(6)      NOT NULL,
    phone         VARCHAR(15)  NOT NULL,
    is_network    TINYINT(1)   NOT NULL DEFAULT 1,
    CONSTRAINT ck_provider_type CHECK (provider_type IN ('HOSPITAL','CLINIC','GARAGE','REPAIR_CENTRE')),
    CONSTRAINT ck_provider_net  CHECK (is_network IN (0,1)),
    CONSTRAINT fk_provider_pincode FOREIGN KEY (pincode) REFERENCES pincode(pincode)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- adjuster: staff who assess claims, each with an approval limit
-- ---------------------------------------------------------------------
CREATE TABLE adjuster (
    adjuster_id    INT AUTO_INCREMENT PRIMARY KEY,
    first_name     VARCHAR(50)   NOT NULL,
    last_name      VARCHAR(50)   NOT NULL,
    email          VARCHAR(120)  NOT NULL,
    phone          VARCHAR(15)   NOT NULL,
    approval_limit DECIMAL(12,2) NOT NULL,
    CONSTRAINT uq_adjuster_email UNIQUE (email),
    CONSTRAINT ck_adjuster_limit CHECK (approval_limit > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- policy: a contract between a customer and the insurer for one product
-- premium_amount is the amount of ONE instalment.
-- ---------------------------------------------------------------------
CREATE TABLE policy (
    policy_id         INT AUTO_INCREMENT PRIMARY KEY,
    policy_number     VARCHAR(40)   NOT NULL DEFAULT (UUID()),   -- placeholder, see sp_sell_policy
    customer_id       INT           NOT NULL,
    type_id           INT           NOT NULL,
    agent_id          INT           NULL,
    start_date        DATE          NOT NULL,
    end_date          DATE          NOT NULL,
    sum_assured       DECIMAL(12,2) NOT NULL,
    premium_amount    DECIMAL(12,2) NOT NULL,
    payment_frequency VARCHAR(12)   NOT NULL DEFAULT 'ANNUAL',
    status            VARCHAR(10)   NOT NULL DEFAULT 'ACTIVE',
    created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_policy_number  UNIQUE (policy_number),
    CONSTRAINT ck_policy_dates   CHECK (end_date > start_date),
    CONSTRAINT ck_policy_amounts CHECK (sum_assured > 0 AND premium_amount > 0),
    CONSTRAINT ck_policy_freq    CHECK (payment_frequency IN ('SINGLE','ANNUAL','HALF_YEARLY','QUARTERLY','MONTHLY')),
    CONSTRAINT ck_policy_status  CHECK (status IN ('ACTIVE','LAPSED','EXPIRED','CANCELLED')),
    CONSTRAINT fk_policy_customer FOREIGN KEY (customer_id) REFERENCES customer(customer_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_policy_type     FOREIGN KEY (type_id) REFERENCES policy_type(type_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_policy_agent    FOREIGN KEY (agent_id) REFERENCES agent(agent_id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- nominee: beneficiaries of a policy (multi-valued attribute split out, 1NF)
-- ---------------------------------------------------------------------
CREATE TABLE nominee (
    nominee_id   INT AUTO_INCREMENT PRIMARY KEY,
    policy_id    INT          NOT NULL,
    full_name    VARCHAR(100) NOT NULL,
    relationship VARCHAR(20)  NOT NULL,
    dob          DATE         NULL,
    share_pct    DECIMAL(5,2) NOT NULL,
    CONSTRAINT ck_nominee_share CHECK (share_pct > 0 AND share_pct <= 100),
    CONSTRAINT ck_nominee_rel   CHECK (relationship IN ('SPOUSE','SON','DAUGHTER','FATHER','MOTHER','BROTHER','SISTER','OTHER')),
    CONSTRAINT fk_nominee_policy FOREIGN KEY (policy_id) REFERENCES policy(policy_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- premium_payment: one row per instalment
-- ---------------------------------------------------------------------
CREATE TABLE premium_payment (
    payment_id     INT AUTO_INCREMENT PRIMARY KEY,
    policy_id      INT           NOT NULL,
    instalment_no  INT           NOT NULL,
    due_date       DATE          NOT NULL,
    amount         DECIMAL(12,2) NOT NULL,
    status         VARCHAR(10)   NOT NULL DEFAULT 'PENDING',
    paid_on        DATE          NULL,
    method         VARCHAR(12)   NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_payment_instalment UNIQUE (policy_id, instalment_no),
    CONSTRAINT ck_payment_amount  CHECK (amount > 0),
    CONSTRAINT ck_payment_status  CHECK (status IN ('PAID','PENDING','FAILED')),
    CONSTRAINT ck_payment_paid_on CHECK ((status = 'PAID') = (paid_on IS NOT NULL)),
    CONSTRAINT ck_payment_method  CHECK (method IS NULL OR method IN ('UPI','CARD','NETBANKING','CASH','CHEQUE','AUTO_DEBIT')),
    CONSTRAINT fk_payment_policy FOREIGN KEY (policy_id) REFERENCES policy(policy_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- claim: fraud_flag = confirmed fraud (ML label); fraud_score = model output
-- ---------------------------------------------------------------------
CREATE TABLE claim (
    claim_id        INT AUTO_INCREMENT PRIMARY KEY,
    claim_number    VARCHAR(40)   NOT NULL DEFAULT (UUID()),     -- placeholder, see sp_file_claim
    policy_id       INT           NOT NULL,
    provider_id     INT           NULL,
    adjuster_id     INT           NULL,
    claim_type      VARCHAR(25)   NOT NULL,
    incident_date   DATE          NOT NULL,
    filed_on        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claimed_amount  DECIMAL(12,2) NOT NULL,
    status          VARCHAR(15)   NOT NULL DEFAULT 'SUBMITTED',
    description     VARCHAR(500)  NULL,
    fraud_flag      TINYINT(1)    NOT NULL DEFAULT 0,
    fraud_score     DECIMAL(5,4)  NULL,
    CONSTRAINT uq_claim_number   UNIQUE (claim_number),
    CONSTRAINT ck_claim_amount   CHECK (claimed_amount > 0),
    CONSTRAINT ck_claim_status   CHECK (status IN ('SUBMITTED','UNDER_REVIEW','APPROVED','REJECTED','PAID')),
    CONSTRAINT ck_claim_type     CHECK (claim_type IN ('HOSPITALISATION','OUTPATIENT','ACCIDENT','THEFT',
                                   'VEHICLE_DAMAGE','DEATH','CRITICAL_ILLNESS','FIRE','FLOOD','BURGLARY',
                                   'TRIP_CANCELLATION','BAGGAGE_LOSS','MEDICAL_EMERGENCY')),
    CONSTRAINT ck_claim_flag     CHECK (fraud_flag IN (0,1)),
    CONSTRAINT ck_claim_score    CHECK (fraud_score IS NULL OR fraud_score BETWEEN 0 AND 1),
    CONSTRAINT ck_claim_filed    CHECK (DATE(filed_on) >= incident_date),
    CONSTRAINT fk_claim_policy   FOREIGN KEY (policy_id) REFERENCES policy(policy_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_claim_provider FOREIGN KEY (provider_id) REFERENCES provider(provider_id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_claim_adjuster FOREIGN KEY (adjuster_id) REFERENCES adjuster(adjuster_id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- claim_document: supporting documents (metadata only; files out of scope)
-- ---------------------------------------------------------------------
CREATE TABLE claim_document (
    doc_id       INT AUTO_INCREMENT PRIMARY KEY,
    claim_id     INT          NOT NULL,
    doc_type     VARCHAR(25)  NOT NULL,
    file_name    VARCHAR(150) NOT NULL,
    uploaded_on  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_doc_type CHECK (doc_type IN ('CLAIM_FORM','MEDICAL_BILL','DISCHARGE_SUMMARY','FIR',
                               'PHOTO','REPAIR_ESTIMATE','DEATH_CERTIFICATE','ID_PROOF','INVOICE','OTHER')),
    CONSTRAINT fk_doc_claim FOREIGN KEY (claim_id) REFERENCES claim(claim_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- claim_assessment: history of adjuster decisions on a claim
-- ---------------------------------------------------------------------
CREATE TABLE claim_assessment (
    assessment_id   INT AUTO_INCREMENT PRIMARY KEY,
    claim_id        INT           NOT NULL,
    adjuster_id     INT           NOT NULL,
    decision        VARCHAR(12)   NOT NULL,
    approved_amount DECIMAL(12,2) NULL,
    remarks         VARCHAR(500)  NULL,
    assessed_on     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_assess_decision CHECK (decision IN ('APPROVED','REJECTED','NEEDS_INFO')),
    CONSTRAINT ck_assess_amount   CHECK ((decision = 'APPROVED') = (approved_amount IS NOT NULL)
                                         AND (approved_amount IS NULL OR approved_amount > 0)),
    CONSTRAINT fk_assess_claim    FOREIGN KEY (claim_id) REFERENCES claim(claim_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_assess_adjuster FOREIGN KEY (adjuster_id) REFERENCES adjuster(adjuster_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- claim_payout: at most one settlement per claim
-- ---------------------------------------------------------------------
CREATE TABLE claim_payout (
    payout_id     INT AUTO_INCREMENT PRIMARY KEY,
    claim_id      INT           NOT NULL,
    amount        DECIMAL(12,2) NOT NULL,
    paid_on       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    method        VARCHAR(20)   NOT NULL DEFAULT 'NEFT',
    reference_no  VARCHAR(40)   NOT NULL,
    CONSTRAINT uq_payout_claim  UNIQUE (claim_id),
    CONSTRAINT uq_payout_ref    UNIQUE (reference_no),
    CONSTRAINT ck_payout_amount CHECK (amount > 0),
    CONSTRAINT ck_payout_method CHECK (method IN ('NEFT','UPI','CHEQUE','DIRECT_TO_PROVIDER')),
    CONSTRAINT fk_payout_claim  FOREIGN KEY (claim_id) REFERENCES claim(claim_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- claim_status_log: audit trail, written only by triggers (BR10)
-- ---------------------------------------------------------------------
CREATE TABLE claim_status_log (
    log_id      INT AUTO_INCREMENT PRIMARY KEY,
    claim_id    INT          NOT NULL,
    old_status  VARCHAR(15)  NULL,
    new_status  VARCHAR(15)  NOT NULL,
    changed_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by  VARCHAR(100) NOT NULL,
    CONSTRAINT fk_log_claim FOREIGN KEY (claim_id) REFERENCES claim(claim_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- fraud_model: registry of trained models. The active row's threshold
-- drives the LOW / MEDIUM / HIGH risk bands in v_claim_summary, so the
-- bands always agree with the threshold the model was tuned for.
-- ---------------------------------------------------------------------
CREATE TABLE fraud_model (
    model_id      INT AUTO_INCREMENT PRIMARY KEY,
    model_name    VARCHAR(60)  NOT NULL,
    threshold     DECIMAL(5,4) NOT NULL,
    test_roc_auc  DECIMAL(5,4) NULL,
    n_trained     INT          NOT NULL,
    trained_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active     TINYINT(1)   NOT NULL DEFAULT 0,
    CONSTRAINT ck_model_threshold CHECK (threshold > 0 AND threshold < 1),
    CONSTRAINT ck_model_active    CHECK (is_active IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
