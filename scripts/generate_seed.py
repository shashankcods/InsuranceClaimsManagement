"""Synthetic seed-data generator (seed 42) -> db/05_seed_data.sql

All data is fictional (e-mails on example.com). Claims enter through the real
workflow: INSERT as SUBMITTED, then status updates, assessments and payouts,
so every trigger (BR1-BR10) fires while the data loads.

Fraud labels carry a deliberate, documented signal (early claims, high claim
ratio, few documents, non-network providers, long filing delays, late
premiums, prior claims) so the ML module has something learnable. Metrics on
this data prove the pipeline works, not real-world accuracy.
"""
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(42)
TODAY = date(2026, 11, 4)
OUT = Path(__file__).resolve().parent.parent / "db" / "05_seed_data.sql"

N_CUSTOMERS = 1600
N_POLICIES = 3500
N_AGENTS = 40
N_PROVIDERS = 120

FIRST_M = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan", "Rohan",
           "Kabir", "Ansh", "Dhruv", "Kartik", "Rahul", "Amit", "Suresh", "Rajesh", "Vikram", "Manish",
           "Nikhil", "Siddharth", "Harsh", "Yash", "Pranav", "Gaurav", "Deepak", "Anil", "Sanjay", "Mohit"]
FIRST_F = ["Ananya", "Diya", "Saanvi", "Aadhya", "Kiara", "Myra", "Anika", "Navya", "Pari", "Riya",
           "Priya", "Neha", "Pooja", "Sneha", "Kavya", "Isha", "Meera", "Shreya", "Tanvi", "Nisha",
           "Sunita", "Anjali", "Divya", "Swati", "Ritika", "Aditi", "Simran", "Komal", "Jyoti", "Payal"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Shah", "Mehta", "Joshi", "Reddy",
        "Nair", "Iyer", "Rao", "Das", "Bose", "Mishra", "Pandey", "Tiwari", "Yadav", "Chauhan",
        "Agarwal", "Saxena", "Srivastava", "Kapoor", "Malhotra", "Banerjee", "Chatterjee", "Pillai", "Menon", "Khan"]
# city -> (state, 3-digit pincode prefix); pincode -> city, state is the D5 dependency
CITIES = {
    "Prayagraj": ("Uttar Pradesh", "211"), "Lucknow": ("Uttar Pradesh", "226"),
    "Kanpur": ("Uttar Pradesh", "208"), "Varanasi": ("Uttar Pradesh", "221"),
    "New Delhi": ("Delhi", "110"), "Mumbai": ("Maharashtra", "400"), "Pune": ("Maharashtra", "411"),
    "Bengaluru": ("Karnataka", "560"), "Chennai": ("Tamil Nadu", "600"), "Hyderabad": ("Telangana", "500"),
    "Kolkata": ("West Bengal", "700"), "Jaipur": ("Rajasthan", "302"), "Ahmedabad": ("Gujarat", "380"),
    "Bhopal": ("Madhya Pradesh", "462"), "Patna": ("Bihar", "800"),
}
CITY_W = [10, 8, 5, 5, 9, 9, 6, 8, 6, 6, 5, 4, 4, 3, 3]
STREETS = ["MG Road", "Civil Lines", "Station Road", "Park Street", "Ring Road", "Gandhi Nagar",
           "Nehru Colony", "Lake View", "Sector 12", "Model Town", "Rajendra Nagar", "Ashok Vihar"]

# type_name, description, min, max, base_rate_pct, max_term_years
POLICY_TYPES = [
    ("Health", "Individual and family health cover", 100000, 2500000, 3.800, 1),
    ("Motor", "Comprehensive private car cover (IDV)", 200000, 2000000, 2.800, 1),
    ("Life", "Term life cover", 1000000, 10000000, 0.600, 30),
    ("Home", "Home structure and contents", 1000000, 10000000, 0.300, 1),
    ("Travel", "Overseas travel medical and trip cover", 500000, 5000000, 4.800, 1),
]
TYPE_W = [34, 27, 15, 10, 14]
CLAIM_TYPES = {
    "Health": [("HOSPITALISATION", 47), ("OUTPATIENT", 45), ("CRITICAL_ILLNESS", 8)],
    "Motor": [("VEHICLE_DAMAGE", 75), ("ACCIDENT", 21), ("THEFT", 4)],
    "Life": [("DEATH", 70), ("CRITICAL_ILLNESS", 30)],
    "Home": [("FIRE", 25), ("FLOOD", 30), ("BURGLARY", 45)],
    "Travel": [("MEDICAL_EMERGENCY", 50), ("TRIP_CANCELLATION", 30), ("BAGGAGE_LOSS", 20)],
}
# expected claims per policy-year, and mean claim size as a fraction of sum assured
CLAIM_FREQ = {"Health": 1.5, "Motor": 0.80, "Life": 0.015, "Home": 0.14, "Travel": 1.0}
CLAIM_SIZE = {"HOSPITALISATION": 0.055, "OUTPATIENT": 0.008, "CRITICAL_ILLNESS": 0.25,
              "VEHICLE_DAMAGE": 0.030, "ACCIDENT": 0.07, "THEFT": 0.85, "DEATH": 1.0,
              "FIRE": 0.05, "FLOOD": 0.025, "BURGLARY": 0.012,
              "MEDICAL_EMERGENCY": 0.008, "TRIP_CANCELLATION": 0.004, "BAGGAGE_LOSS": 0.002}
DOCS = {"HOSPITALISATION": ["CLAIM_FORM", "MEDICAL_BILL", "DISCHARGE_SUMMARY", "ID_PROOF"],
        "OUTPATIENT": ["CLAIM_FORM", "MEDICAL_BILL", "ID_PROOF"],
        "CRITICAL_ILLNESS": ["CLAIM_FORM", "MEDICAL_BILL", "DISCHARGE_SUMMARY", "ID_PROOF"],
        "VEHICLE_DAMAGE": ["CLAIM_FORM", "PHOTO", "REPAIR_ESTIMATE", "INVOICE"],
        "ACCIDENT": ["CLAIM_FORM", "FIR", "PHOTO", "REPAIR_ESTIMATE"],
        "THEFT": ["CLAIM_FORM", "FIR", "ID_PROOF", "INVOICE"],
        "DEATH": ["CLAIM_FORM", "DEATH_CERTIFICATE", "ID_PROOF", "MEDICAL_BILL"],
        "FIRE": ["CLAIM_FORM", "FIR", "PHOTO", "REPAIR_ESTIMATE"],
        "FLOOD": ["CLAIM_FORM", "PHOTO", "REPAIR_ESTIMATE", "INVOICE"],
        "BURGLARY": ["CLAIM_FORM", "FIR", "INVOICE", "PHOTO"],
        "MEDICAL_EMERGENCY": ["CLAIM_FORM", "MEDICAL_BILL", "ID_PROOF"],
        "TRIP_CANCELLATION": ["CLAIM_FORM", "INVOICE", "ID_PROOF"],
        "BAGGAGE_LOSS": ["CLAIM_FORM", "INVOICE", "OTHER"]}
FREQ_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "HALF_YEARLY": 6, "ANNUAL": 12}
PER_YEAR = {"MONTHLY": 12, "QUARTERLY": 4, "HALF_YEARLY": 2, "ANNUAL": 1}


def q(v):
    """SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return f"{v:.2f}" if isinstance(v, float) else str(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.isoformat() + "'"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def bulk_insert(out, table, cols, rows, chunk=500):
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n" +
                   ",\n".join("(" + ", ".join(q(v) for v in r) + ")" for r in part) + ";")


def add_months(d, m):
    y, mo = divmod(d.month - 1 + m, 12)
    y += d.year
    mo += 1
    day = min(d.day, [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1])
    return date(y, mo, day)


def rand_date(a, b):
    return a + timedelta(days=random.randint(0, max((b - a).days, 0)))


def rand_dt(d, h0=9, h1=19):
    return datetime(d.year, d.month, d.day, random.randint(h0, h1), random.randint(0, 59), random.randint(0, 59))


def phone():
    return str(random.choice([6, 7, 8, 9])) + "".join(str(random.randint(0, 9)) for _ in range(9))


def round_amt(x, step=100):
    return float(max(step, round(x / step) * step))


def main():
    out = ["-- 05_seed_data.sql: GENERATED by scripts/generate_seed.py (seed 42). Do not edit by hand.",
           "-- Synthetic, fictional data. Reference date (today) = " + TODAY.isoformat(),
           "SET @audit_ts = NULL;", "START TRANSACTION;"]

    # ---------------- policy types ----------------
    bulk_insert(out, "policy_type",
                ["type_id", "type_name", "description", "min_sum_assured", "max_sum_assured", "base_rate_pct", "max_term_years"],
                [(i + 1, n, d, float(lo), float(hi), r, t) for i, (n, d, lo, hi, r, t) in enumerate(POLICY_TYPES)])
    type_by_id = {i + 1: t for i, t in enumerate(POLICY_TYPES)}

    used_emails = set()

    def email(fn, ln, domain="example.com"):
        base = f"{fn}.{ln}".lower()
        e, n = f"{base}@{domain}", 1
        while e in used_emails:
            n += 1
            e = f"{base}{n}@{domain}"
        used_emails.add(e)
        return e

    # ---------------- agents (5 managers, 35 reporting) ----------------
    agents = []
    city_names = list(CITIES)
    for i in range(1, N_AGENTS + 1):
        g = random.random() < 0.5
        fn = random.choice(FIRST_M if g else FIRST_F)
        ln = random.choice(LAST)
        mgr = None if i <= 5 else random.randint(1, 5)
        agents.append((i, fn, ln, email(fn, ln, "agents.example.com"), phone(),
                       random.choices(city_names, CITY_W)[0], rand_date(date(2015, 1, 1), date(2022, 6, 30)),
                       round(random.uniform(8, 12) if i <= 5 else random.uniform(4, 15), 2), mgr))
    bulk_insert(out, "agent", ["agent_id", "first_name", "last_name", "email", "phone", "branch_city",
                               "hire_date", "commission_rate", "manager_id"], agents)

    # ---------------- pincodes (pincode -> city, state) ----------------
    # 30 pincodes per city: prefix + 001..030
    pincodes = [(pre + f"{k:03d}", city, st) for city, (st, pre) in CITIES.items() for k in range(1, 31)]
    bulk_insert(out, "pincode", ["pincode", "city", "state"], pincodes)

    def pin_for(city):
        return CITIES[city][1] + f"{random.randint(1, 30):03d}"

    # ---------------- customers ----------------
    customers = []
    cust_dob = {}
    for i in range(1, N_CUSTOMERS + 1):
        gender = random.choices(["M", "F", "O"], [49, 49, 2])[0]
        fn = random.choice(FIRST_M if gender == "M" else FIRST_F if gender == "F" else FIRST_M + FIRST_F)
        ln = random.choice(LAST)
        dob = rand_date(date(1955, 1, 1), date(2003, 12, 31))
        cust_dob[i] = dob
        city = random.choices(city_names, CITY_W)[0]
        customers.append((i, fn, ln, dob, gender, email(fn, ln), phone(),
                          f"{random.randint(1, 450)}, {random.choice(STREETS)}", pin_for(city),
                          rand_dt(rand_date(date(2022, 6, 1), date(2026, 10, 1)))))
    bulk_insert(out, "customer", ["customer_id", "first_name", "last_name", "dob", "gender", "email", "phone",
                                  "address_line", "pincode", "created_at"], customers)

    # ---------------- providers ----------------
    providers = []
    pv_by_kind = {"MED": [], "AUTO": []}
    for i in range(1, N_PROVIDERS + 1):
        city = random.choices(city_names, CITY_W)[0]
        if i <= 70:
            kind = random.choices(["HOSPITAL", "CLINIC"], [70, 30])[0]
            name = f"{random.choice(['City', 'Sunrise', 'Lifeline', 'Apex', 'Care', 'Metro', 'Shanti', 'Global', 'Sanjeevani', 'Medicity'])} {'Hospital' if kind == 'HOSPITAL' else 'Clinic'}, {city}"
            pv_by_kind["MED"].append(i)
        else:
            kind = random.choices(["GARAGE", "REPAIR_CENTRE"], [60, 40])[0]
            name = f"{random.choice(['Speed', 'Prime', 'Royal', 'Highway', 'Star', 'Classic', 'Express', 'Shree'])} {'Motors' if kind == 'GARAGE' else 'Repair Centre'}, {city}"
            pv_by_kind["AUTO"].append(i)
        providers.append((i, name, kind, pin_for(city), phone(), 1 if random.random() < 0.78 else 0))
    bulk_insert(out, "provider", ["provider_id", "name", "provider_type", "pincode", "phone", "is_network"], providers)
    provider_net = {p[0]: p[5] for p in providers}

    # ---------------- adjusters (limit tiers) ----------------
    limits = [200000] * 4 + [500000] * 4 + [1500000] * 3 + [5000000] * 2 + [25000000] * 2
    adjusters = []
    for i, lim in enumerate(limits, start=1):
        fn = random.choice(FIRST_M + FIRST_F)
        ln = random.choice(LAST)
        adjusters.append((i, fn, ln, email(fn, ln, "claims.example.com"), phone(), float(lim)))
    bulk_insert(out, "adjuster", ["adjuster_id", "first_name", "last_name", "email", "phone", "approval_limit"], adjusters)

    # ---------------- policies, nominees, premiums ----------------
    policies, nominees, payments = [], [], []
    pol_info = {}
    pay_id = 0
    for pid in range(1, N_POLICIES + 1):
        tid = random.choices(range(1, 6), TYPE_W)[0]
        tname, _, lo, hi, rate, _ = type_by_id[tid]
        cid = random.randint(1, N_CUSTOMERS)
        # skew start dates towards the recent past
        start = TODAY - timedelta(days=int(1400 * random.random() ** 1.6))
        if tname == "Life":
            term_m = random.choice([10, 15, 20, 25, 30]) * 12
            freq = random.choices(["ANNUAL", "HALF_YEARLY", "QUARTERLY", "MONTHLY"], [50, 15, 15, 20])[0]
            sa = round_amt(random.choice([10, 20, 25, 50, 75, 100]) * 100000, 1000)
        elif tname == "Travel":
            term_m = random.choices([1, 2], [75, 25])[0]   # trip cover in whole months, as sp_sell_policy
            freq = "SINGLE"
            sa = round_amt(random.choice([5, 10, 25, 50]) * 100000, 1000)
        else:
            term_m = 12
            freq = random.choices(["ANNUAL", "HALF_YEARLY", "QUARTERLY", "MONTHLY"], [55, 15, 15, 15])[0]
            if tname == "Health":
                sa = round_amt(random.choice([1, 2, 3, 5, 5, 10, 10, 15, 20, 25]) * 100000, 1000)
            elif tname == "Motor":
                sa = round_amt(random.uniform(lo, 1200000), 1000)
            else:
                sa = round_amt(random.uniform(lo, 6000000), 10000)
        # same pricing as sp_sell_policy / fn_annual_premium
        end = add_months(start, term_m) - timedelta(days=1)
        age = (start - cust_dob[cid]).days // 365
        load = 1 + max(age - 30, 0) * 0.02 if tname in ("Health", "Life") else 1
        annual = round(sa * rate / 100 * load, 2)
        inst = round(annual * term_m / 12, 2) if freq == "SINGLE" else round(annual / PER_YEAR[freq], 2)
        inst = max(inst, 1.0)
        agent = random.randint(1, N_AGENTS) if random.random() < 0.92 else None
        pol_num = f"POL-{start.year}-{pid:06d}"
        created = rand_dt(start - timedelta(days=random.randint(0, 10)))
        policies.append([pid, pol_num, cid, tid, agent, start, end, sa, inst, freq, "ACTIVE", created])

        # premium behaviour: ~9% of customers stop paying at some point (drives lapses)
        bad_payer = random.random() < 0.09
        stop_after = random.randint(1, 6) if bad_payer else 10 ** 6
        chronic_late = random.random() < 0.15
        n, due, late_count = 0, start, 0
        horizon = min(end, TODAY + timedelta(days=30))
        while due <= horizon:
            n += 1
            pay_id += 1
            if due > TODAY or n > stop_after:
                status, paid, method = "PENDING", None, None
            else:
                delay = random.randint(5, 45) if chronic_late and random.random() < 0.6 else random.randint(-10, 3)
                paid = due + timedelta(days=delay)
                if paid > TODAY:
                    status, paid, method = "PENDING", None, None
                elif random.random() < 0.02:
                    status, paid, method = "FAILED", None, random.choice(["CARD", "AUTO_DEBIT"])
                else:
                    status, method = "PAID", random.choice(["UPI", "CARD", "NETBANKING", "AUTO_DEBIT", "CASH", "CHEQUE"])
                    if delay > 0:
                        late_count += 1
            payments.append((pay_id, pid, n, due, inst, status, paid, method,
                             rand_dt(due - timedelta(days=15)) if n > 1 else created))
            if freq == "SINGLE":
                break
            due = add_months(start, FREQ_MONTHS[freq] * n)
        pol_info[pid] = dict(cid=cid, tname=tname, start=start, end=end, sa=sa, late=late_count,
                             paid_out=0.0, created=created)

        if tname in ("Life", "Health") and random.random() < 0.85:
            k = random.choices([1, 2, 3], [55, 35, 10])[0]
            shares = {1: [100], 2: random.choice([[50, 50], [60, 40], [70, 30]]), 3: random.choice([[40, 30, 30], [50, 25, 25], [34, 33, 33]])}[k]
            for s in shares:
                rel = random.choice(["SPOUSE", "SON", "DAUGHTER", "FATHER", "MOTHER", "BROTHER", "SISTER"])
                fn = random.choice(FIRST_M + FIRST_F)
                nominees.append((pid, f"{fn} {random.choice(LAST)}", rel, rand_date(date(1950, 1, 1), date(2015, 1, 1)), float(s)))

    bulk_insert(out, "policy", ["policy_id", "policy_number", "customer_id", "type_id", "agent_id", "start_date", "end_date",
                                "sum_assured", "premium_amount", "payment_frequency", "status", "created_at"], policies)
    bulk_insert(out, "nominee", ["policy_id", "full_name", "relationship", "dob", "share_pct"], nominees)
    bulk_insert(out, "premium_payment", ["payment_id", "policy_id", "instalment_no", "due_date", "amount", "status",
                                         "paid_on", "method", "created_at"], payments)

    # ---------------- claims through the real workflow ----------------
    claim_rows, workflow = [], []
    docs = []
    cust_claims = {}
    cid_seq = 0
    stats = {"fraud": 0, "total": 0}
    adj_by_limit = sorted(adjusters, key=lambda a: a[5])
    premium_by_type, paid_by_type = {}, {}
    for p in payments:
        if p[5] == "PAID":
            t = pol_info[p[1]]["tname"]
            premium_by_type[t] = premium_by_type.get(t, 0) + p[4]

    events = []  # (filed_on, policy_id, ...) generated per policy then sorted by time
    for pid, info in pol_info.items():
        exp_end = min(info["end"], TODAY - timedelta(days=1))
        if exp_end <= info["start"]:
            continue
        years = (exp_end - info["start"]).days / 365.25
        lam = CLAIM_FREQ[info["tname"]] * (years if info["tname"] != "Travel" else 1.0)
        k = 0
        L, pr = math.exp(-lam), 1.0
        while True:  # Poisson draw
            pr *= random.random()
            if pr < L:
                break
            k += 1
        for _ in range(k):
            events.append((pid, rand_date(info["start"], exp_end)))
    events.sort(key=lambda e: e[1])

    for pid, incident in events:
        info = pol_info[pid]
        tname = info["tname"]
        ctype = random.choices([c for c, _ in CLAIM_TYPES[tname]], [w for _, w in CLAIM_TYPES[tname]])[0]
        prior = cust_claims.get(info["cid"], 0)

        # latent fraud propensity with a learnable signal
        days_since_start = (incident - info["start"]).days
        early = 1 if days_since_start < 45 else 0
        z = -3.35 + 1.5 * early + 0.25 * min(prior, 4) + 0.35 * min(info["late"], 4)
        is_fraud_like = random.random() < 1 / (1 + math.exp(-z))
        delay = random.randint(15, 75) if (is_fraud_like and random.random() < 0.55) else random.randint(0, 12)
        filed_date = incident + timedelta(days=delay)
        if filed_date > TODAY:
            filed_date = TODAY
        filed = rand_dt(filed_date)
        if filed > datetime(TODAY.year, TODAY.month, TODAY.day, 23, 0):
            continue

        size = CLAIM_SIZE[ctype] * random.lognormvariate(0, 0.45) * (1.6 if is_fraud_like else 1.0)
        remaining = info["sa"] - info["paid_out"]
        amount = min(round_amt(info["sa"] * min(size, 1.0)), info["sa"])
        if ctype == "DEATH":
            amount = info["sa"]
        if remaining < 1000:
            continue
        amount = min(amount, remaining)

        if ctype in ("HOSPITALISATION", "OUTPATIENT", "CRITICAL_ILLNESS", "MEDICAL_EMERGENCY"):
            pool = pv_by_kind["MED"]
        elif ctype in ("VEHICLE_DAMAGE", "ACCIDENT"):
            pool = pv_by_kind["AUTO"]
        else:
            pool = None
        provider = None
        if pool:
            if is_fraud_like and random.random() < 0.6:
                nn = [p for p in pool if provider_net[p] == 0]
                provider = random.choice(nn)
            else:
                provider = random.choice(pool)

        # final label: confirmed fraud (the latent propensity is not perfectly observed)
        fraud = is_fraud_like and random.random() < 0.80
        cid_seq += 1
        claim_id = cid_seq
        stats["total"] += 1
        stats["fraud"] += fraud
        cust_claims[info["cid"]] = prior + 1
        claim_rows.append((claim_id, f"CLM-{filed.year}-{claim_id:06d}", pid, provider, ctype, incident, filed,
                           amount, f"{ctype.replace('_', ' ').title()} claim reported by policy holder"))

        need = DOCS[ctype]
        n_docs = random.randint(1, 2) if (is_fraud_like and random.random() < 0.65) else random.randint(len(need) - 1, len(need))
        for j, dt in enumerate(need[:n_docs]):
            docs.append((claim_id, dt, f"{dt.lower()}_{claim_id}.pdf", filed + timedelta(minutes=5 * j + 1)))

        # workflow progress depends on how long ago the claim was filed
        age_days = (TODAY - filed_date).days
        steps = []
        if age_days < 4 and random.random() < 0.7:
            final = "SUBMITTED"
        elif age_days < 25 and random.random() < 0.6:
            final = "UNDER_REVIEW"
        else:
            if fraud:
                final = "REJECTED" if random.random() < 0.85 else "PAID"
            else:
                r = random.random()
                # approved-but-unpaid only for recent decisions; older approvals have been paid out
                final = "REJECTED" if r < 0.12 else ("APPROVED" if age_days < 40 and r < 0.37 else "PAID")
        if final == "SUBMITTED":
            workflow.append((filed, claim_id, steps, final, None))
            continue
        adj_cands = [a for a in adj_by_limit if a[5] >= amount]
        adj = random.choice(adj_cands[:6]) if len(adj_cands) > 6 else adj_cands[0]
        review_at = filed + timedelta(days=random.randint(1, 3), hours=random.randint(1, 6))
        steps.append(("REVIEW", review_at, adj[0]))
        if final in ("APPROVED", "PAID"):
            approved = amount if random.random() < 0.55 else round_amt(amount * random.uniform(0.6, 0.98))
            approve_at = review_at + timedelta(days=random.randint(2, 15))
            steps.append(("APPROVE", approve_at, adj[0], approved))
            if final == "PAID":
                pay_at = approve_at + timedelta(days=random.randint(1, 7))
                steps.append(("PAY", pay_at, approved))
                info["paid_out"] += approved
                paid_by_type[tname] = paid_by_type.get(tname, 0) + approved
        elif final == "REJECTED":
            if random.random() < 0.25:
                steps.append(("NEEDS_INFO", review_at + timedelta(days=random.randint(1, 4)), adj[0]))
            steps.append(("REJECT", review_at + timedelta(days=random.randint(5, 20)), adj[0], fraud))
        # payout/decision timestamps must not run into the future
        steps = [s for s in steps if s[1].date() <= TODAY] if steps else steps
        workflow.append((filed, claim_id, steps, final, fraud))

    bulk_insert(out, "claim", ["claim_id", "claim_number", "policy_id", "provider_id", "claim_type", "incident_date",
                               "filed_on", "claimed_amount", "description"], claim_rows)
    bulk_insert(out, "claim_document", ["claim_id", "doc_type", "file_name", "uploaded_on"], docs)

    # replay the workflow statement by statement so the triggers enforce every step
    out.append("-- ---- claim workflow replay (fires BR4-BR7, BR10) ----")
    pay_ref = 0
    for filed, claim_id, steps, final, fraud in workflow:
        for s in steps:
            kind, ts = s[0], s[1]
            out.append(f"SET @audit_ts = {q(ts)};")
            if kind == "REVIEW":
                out.append(f"UPDATE claim SET adjuster_id = {s[2]}, status = 'UNDER_REVIEW' WHERE claim_id = {claim_id};")
            elif kind == "NEEDS_INFO":
                out.append("INSERT INTO claim_assessment (claim_id, adjuster_id, decision, remarks, assessed_on) VALUES "
                           f"({claim_id}, {s[2]}, 'NEEDS_INFO', 'Additional documents requested', {q(ts)});")
            elif kind == "APPROVE":
                out.append("INSERT INTO claim_assessment (claim_id, adjuster_id, decision, approved_amount, remarks, assessed_on) VALUES "
                           f"({claim_id}, {s[2]}, 'APPROVED', {q(float(s[3]))}, 'Claim verified against documents', {q(ts)});")
                out.append(f"UPDATE claim SET status = 'APPROVED' WHERE claim_id = {claim_id};")
            elif kind == "REJECT":
                remark = "Suspected fraud: inconsistent documents" if s[3] else "Not covered under policy terms"
                out.append("INSERT INTO claim_assessment (claim_id, adjuster_id, decision, remarks, assessed_on) VALUES "
                           f"({claim_id}, {s[2]}, 'REJECTED', {q(remark)}, {q(ts)});")
                out.append(f"UPDATE claim SET status = 'REJECTED' WHERE claim_id = {claim_id};")
            elif kind == "PAY":
                pay_ref += 1
                out.append("INSERT INTO claim_payout (claim_id, amount, paid_on, method, reference_no) VALUES "
                           f"({claim_id}, {q(float(s[2]))}, {q(ts)}, {q(random.choice(['NEFT', 'NEFT', 'UPI', 'DIRECT_TO_PROVIDER', 'CHEQUE']))}, "
                           f"'PAY-{ts.strftime('%Y%m%d')}-{claim_id:06d}');")
        # fraud is only "confirmed" once the claim was actually decided (steps dated in the
        # future were dropped above, which can leave the claim still under review)
        if fraud and steps and steps[-1][0] in ("REJECT", "PAY"):
            out.append(f"UPDATE claim SET fraud_flag = 1 WHERE claim_id = {claim_id};")
    out.append("SET @audit_ts = NULL;")

    # ---------------- end-of-load batch jobs ----------------
    # cancel only clean, current policies: no claims and nothing overdue
    claimed = {c[2] for c in claim_rows}
    overdue = {p[1] for p in payments if p[5] != "PAID" and p[3] < TODAY}
    cancel = random.sample([p[0] for p in policies
                            if p[6] > TODAY and p[0] not in claimed and p[0] not in overdue], 40)
    out.append("-- a few customer cancellations")
    out.append(f"UPDATE policy SET status = 'CANCELLED' WHERE policy_id IN ({', '.join(map(str, sorted(cancel)))});")
    out.append("COMMIT;")
    out.append("-- premium lifecycle batch jobs (F3)")
    out.append("CALL sp_expire_policies(@expired);")
    out.append("CALL sp_lapse_overdue_policies(30, @lapsed);")
    out.append("SELECT @expired AS policies_expired, @lapsed AS policies_lapsed;")

    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    n_resolved = sum(1 for w in workflow if w[3] in ("REJECTED", "PAID", "APPROVED"))
    print(f"customers={len(customers)} policies={len(policies)} nominees={len(nominees)} "
          f"instalments={len(payments)} claims={len(claim_rows)} docs={len(docs)} resolved={n_resolved}")
    print(f"fraud rate={stats['fraud'] / max(stats['total'], 1):.3f}")
    for t in premium_by_type:
        print(f"  loss ratio {t:7s}: {100 * paid_by_type.get(t, 0) / premium_by_type[t]:6.1f}%  "
              f"(premium {premium_by_type[t]:,.0f}, paid {paid_by_type.get(t, 0):,.0f})")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
