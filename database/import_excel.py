"""
Import historical sales data from Excel into the Jay's Tire Shop database.

Usage:
    python import_excel.py                          # uses default paths below
    python import_excel.py path/to/excel.xlsx       # custom Excel path
    python import_excel.py path/to/excel.xlsx jaystire.db  # custom both

The Excel columns (row 1 = headers, data starts row 2):
    A = form timestamp (ignored)
    B = Store ("Tire Shop #1/2/3")
    C = Transaction Date
    D = Receipt #
    E = Labor ($)
    F = Used Tire ($)
    G = Used Tire Qty
    H = New Tire ($)
    I = New Tire Qty
    J = Alignment ($)
    K = Other Service ($)
    L = Tire Size (format: 2055517 → 205/55/17)
    M = Payment Method (Cash / Card)
    N = Cost ($)
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# ── Install openpyxl if missing ───────────────────────────────────────────────
try:
    import openpyxl
except ImportError:
    print("openpyxl not found — installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl

# ── Default paths ─────────────────────────────────────────────────────────────
DEFAULT_EXCEL = Path(r"C:\Users\ruizk\OneDrive\Desktop\Jaimie\Jay's Tire Shop\Jays Tire Sales Report(20260325).xlsx")
DEFAULT_DB    = Path(__file__).parent / "jaystire.db"

# ── Helpers ───────────────────────────────────────────────────────────────────
STORE_MAP = {
    'tire shop #1': 1, 'tire shop #2': 2, 'tire shop #3': 3,
}

def parse_store(val):
    if val is None: return None
    return STORE_MAP.get(str(val).strip().lower())

def parse_float(val):
    if val is None or val == '': return None
    try: return float(val)
    except: return None

def parse_int(val):
    if val is None or val == '': return None
    try: return int(float(val))
    except: return None

def parse_date(val):
    if val is None: return None
    if isinstance(val, datetime): return val.strftime('%Y-%m-%d')
    if hasattr(val, 'date'):      return val.date().strftime('%Y-%m-%d')
    try:
        s = str(val).split()[0]
        return datetime.strptime(s, '%Y-%m-%d').strftime('%Y-%m-%d')
    except:
        return None

def tire_size_fmt(val):
    """Convert 2055517 → 205/55/17.  Returns None if can't parse."""
    if val is None: return None
    try:
        s = str(int(float(val))).zfill(7)
        if len(s) == 7:
            return f"{s[0:3]}/{s[3:5]}/{s[5:7]}"
    except:
        pass
    return None

def parse_payment(val):
    if val is None: return 'Cash'
    return 'Card' if str(val).strip().lower() == 'card' else 'Cash'

# ── Main import ───────────────────────────────────────────────────────────────
def run(excel_path=DEFAULT_EXCEL, db_path=DEFAULT_DB):
    print(f"Excel : {excel_path}")
    print(f"DB    : {db_path}\n")

    wb   = openpyxl.load_workbook(excel_path, data_only=True, read_only=True)
    ws   = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()
    print(f"Rows in Excel: {len(rows)}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    imported = skipped = errors = 0
    null_counter = {}   # tracks generated receipt#s for rows with no receipt

    for i, row in enumerate(rows):
        try:
            # ── Parse ─────────────────────────────────────────────────────────
            store     = parse_store(row[1])
            date      = parse_date(row[2])
            receipt_r = row[3]               # raw — may be int or None
            labor     = parse_float(row[4])
            used_amt  = parse_float(row[5])
            used_qty  = parse_int(row[6]) or 1
            new_amt   = parse_float(row[7])
            new_qty   = parse_int(row[8])  or 1
            align_amt = parse_float(row[9])
            other_amt = parse_float(row[10])
            tire_size = tire_size_fmt(row[11])
            payment   = parse_payment(row[12])
            cost      = parse_float(row[13]) or 0.0

            # ── Skip rows that can't be placed ────────────────────────────────
            if store is None or date is None:
                skipped += 1
                continue

            revenue = sum(x for x in [labor, used_amt, new_amt, align_amt, other_amt] if x)
            if revenue == 0:
                skipped += 1
                continue

            # ── Build receipt number ──────────────────────────────────────────
            if receipt_r is not None:
                receipt = f"EX{store}-{int(receipt_r)}"
            else:
                key = f"{store}-{date}"
                null_counter[key] = null_counter.get(key, 0) + 1
                date_compact = date.replace('-', '')[2:]          # YYMMDD
                receipt = f"EX{store}-{date_compact}-{null_counter[key]:03d}"

            # ── Skip duplicates already in DB ─────────────────────────────────
            cur.execute(
                "SELECT id FROM transactions WHERE receipt_number = ? AND store_number = ?",
                (receipt, store)
            )
            if cur.fetchone():
                skipped += 1
                continue

            # ── Financials ────────────────────────────────────────────────────
            # Excel amounts are the actual collected totals — do not add tax
            # on top (some card amounts in the Excel already include 8.6% tax).
            subtotal = revenue
            tax      = 0.0
            total    = subtotal
            profit   = subtotal - cost

            # ── Insert transaction ────────────────────────────────────────────
            cur.execute("""
                INSERT INTO transactions
                    (receipt_number, store_number, transaction_date, payment_method,
                     subtotal, tax, total, cost, profit, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'excel')
            """, (receipt, store, date, payment, subtotal, tax, total, cost, profit))

            tx_id = cur.lastrowid

            # ── Insert line items ─────────────────────────────────────────────
            if labor:
                cur.execute("""
                    INSERT INTO transaction_items
                        (transaction_id, item_type, description, quantity, unit_price, total_price)
                    VALUES (?, 'labor', 'Labor', 1, ?, ?)
                """, (tx_id, labor, labor))

            if used_amt:
                up = used_amt / used_qty
                cur.execute("""
                    INSERT INTO transaction_items
                        (transaction_id, item_type, description, tire_size,
                         quantity, unit_price, total_price)
                    VALUES (?, 'used_tire', ?, ?, ?, ?, ?)
                """, (tx_id, f"USED Tire {tire_size or ''}".strip(),
                      tire_size, used_qty, up, used_amt))

            if new_amt:
                up = new_amt / new_qty
                cur.execute("""
                    INSERT INTO transaction_items
                        (transaction_id, item_type, description, tire_size,
                         quantity, unit_price, total_price)
                    VALUES (?, 'new_tire', ?, ?, ?, ?, ?)
                """, (tx_id, f"NEW Tire {tire_size or ''}".strip(),
                      tire_size, new_qty, up, new_amt))

            if align_amt:
                cur.execute("""
                    INSERT INTO transaction_items
                        (transaction_id, item_type, description, quantity, unit_price, total_price)
                    VALUES (?, 'alignment', 'Alignment', 1, ?, ?)
                """, (tx_id, align_amt, align_amt))

            if other_amt:
                cur.execute("""
                    INSERT INTO transaction_items
                        (transaction_id, item_type, description, quantity, unit_price, total_price)
                    VALUES (?, 'other', 'Other Service', 1, ?, ?)
                """, (tx_id, other_amt, other_amt))

            imported += 1
            if imported % 500 == 0:
                conn.commit()
                print(f"  {imported} imported so far...")

        except Exception as e:
            errors += 1
            print(f"  Row {i + 2} error: {e}")
            continue

    conn.commit()
    conn.close()

    print(f"\n✓ Done!")
    print(f"  Imported : {imported:,}")
    print(f"  Skipped  : {skipped:,}  (duplicates or empty rows)")
    print(f"  Errors   : {errors}")
    if imported:
        print(f"\nOpen reports.html to see the full history.")

if __name__ == "__main__":
    excel = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EXCEL
    db    = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DB
    run(excel, db)
