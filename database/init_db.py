"""
Initialize the Jay's Tire Shop database and load historical data from Excel.
"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

# Database path
DB_PATH = Path(__file__).parent / "jaystire.db"
EXCEL_PATH = Path(r"C:\Users\ruizk\Downloads\Jays Tire Sales Report(1).xlsx")


def create_database():
    """Create the database schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Transactions table - one row per receipt/sale
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_number TEXT NOT NULL,
            store_number INTEGER NOT NULL,
            transaction_date DATE NOT NULL,
            payment_method TEXT NOT NULL,
            subtotal REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            total REAL DEFAULT 0,
            cost REAL DEFAULT 0,
            profit REAL DEFAULT 0,
            -- Vehicle info (from POS, may be null for historical)
            vehicle_make TEXT,
            vehicle_model TEXT,
            vehicle_year INTEGER,
            license_plate TEXT,
            -- Employee and notes
            employee_id TEXT,
            internal_notes TEXT,
            terminal_code TEXT,
            -- Metadata
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'pos'  -- 'pos' or 'historical'
        )
    """)

    # Transaction items table - line items for each transaction
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,  -- 'used_tire', 'new_tire', 'labor', 'alignment', 'other'
            description TEXT,
            tire_size TEXT,
            tire_positions TEXT,  -- comma-separated: 'LF,RF,LR,RR'
            quantity INTEGER DEFAULT 1,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            cost REAL DEFAULT 0,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        )
    """)

    # New tire inventory
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS new_tire_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_number INTEGER NOT NULL,
            brand TEXT NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            cost_per_tire REAL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(store_number, brand, size)
        )
    """)

    # Create indexes for common queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_store ON transactions(store_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_receipt ON transactions(receipt_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_plate ON transactions(license_plate)")

    for col_sql in [
        "ALTER TABLE transaction_items ADD COLUMN brand TEXT",
        "ALTER TABLE transaction_items ADD COLUMN from_inventory INTEGER DEFAULT 0"
    ]:
        try:
            cursor.execute(col_sql)
        except Exception:
            pass

    conn.commit()
    conn.close()
    print(f"Database created at: {DB_PATH}")


def parse_store_number(store_str):
    """Extract store number from 'Tire Shop #1' format."""
    if pd.isna(store_str):
        return None
    return int(store_str.replace("Tire Shop #", ""))


def parse_tire_size(size_val):
    """Convert numeric tire size (2657516) to standard format (265/75/16)."""
    if pd.isna(size_val):
        return None
    size_str = str(int(size_val)) if isinstance(size_val, float) else str(size_val)
    # Format: width(3) / aspect(2) / rim(2) -> e.g., 2657516 = 265/75/16
    if len(size_str) == 7:
        return f"{size_str[:3]}/{size_str[3:5]}/{size_str[5:]}"
    elif len(size_str) == 6:
        return f"{size_str[:2]}/{size_str[2:4]}/{size_str[4:]}"
    return size_str


def generate_receipt_number(store, date, receipt_num):
    """Generate receipt number in format: store-MMDDYY-### or use existing."""
    if pd.notna(receipt_num):
        return f"{store}-{int(receipt_num)}"
    # Fallback format
    if pd.notna(date):
        date_str = date.strftime("%m%d%y")
        return f"{store}-{date_str}-000"
    return f"{store}-000000-000"


def load_historical_data():
    """Load historical data from Excel into the database."""
    print(f"Loading data from: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Track statistics
    stats = {
        'transactions': 0,
        'items': 0,
        'skipped': 0
    }

    for idx, row in df.iterrows():
        try:
            # Extract basic info
            store_num = parse_store_number(row['Tire Shop #'])
            trans_date = row['Date.1']
            payment = row['Payment Method']
            receipt_num = row['Receipt #']

            # Skip rows with missing critical data
            if store_num is None or pd.isna(trans_date):
                stats['skipped'] += 1
                continue

            # Clean payment method
            if pd.isna(payment):
                payment = 'Cash'
            else:
                payment = payment.strip()

            # Calculate totals from the row
            labor = row['Labor ($)'] if pd.notna(row['Labor ($)']) else 0
            used_tire = row['Used Tire  ($) '] if pd.notna(row['Used Tire  ($) ']) else 0
            new_tire_val = row['New Tire ($)']
            new_tire = float(new_tire_val) if pd.notna(new_tire_val) and str(new_tire_val).replace('.','').isdigit() else 0
            alignment = row['Alignment ($)'] if pd.notna(row['Alignment ($)']) else 0
            other = row['Other Service ($)'] if pd.notna(row['Other Service ($)']) else 0

            total = labor + used_tire + new_tire + alignment + other
            cost = row['Cost ($)'] if pd.notna(row['Cost ($)']) else 0
            profit = row['Profit'] if pd.notna(row['Profit']) else total - cost

            # Generate receipt number
            receipt = generate_receipt_number(store_num, trans_date, receipt_num)

            # Insert transaction
            cursor.execute("""
                INSERT INTO transactions
                (receipt_number, store_number, transaction_date, payment_method,
                 subtotal, tax, total, cost, profit, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'historical')
            """, (receipt, store_num, trans_date.strftime("%Y-%m-%d"), payment,
                  total, 0, total, cost, profit))

            transaction_id = cursor.lastrowid
            stats['transactions'] += 1

            # Insert line items based on what's in the row
            tire_size = parse_tire_size(row['Tire Size'])

            if labor > 0:
                cursor.execute("""
                    INSERT INTO transaction_items
                    (transaction_id, item_type, description, quantity, unit_price, total_price)
                    VALUES (?, 'labor', 'Labor', 1, ?, ?)
                """, (transaction_id, labor, labor))
                stats['items'] += 1

            if used_tire > 0:
                qty = int(row['Used Tire (Quantity)']) if pd.notna(row['Used Tire (Quantity)']) else 1
                cursor.execute("""
                    INSERT INTO transaction_items
                    (transaction_id, item_type, description, tire_size, quantity, unit_price, total_price)
                    VALUES (?, 'used_tire', 'Used Tire', ?, ?, ?, ?)
                """, (transaction_id, tire_size, qty, used_tire/qty if qty > 0 else used_tire, used_tire))
                stats['items'] += 1

            if new_tire > 0:
                qty = int(row['New Tire (Quantity) ']) if pd.notna(row['New Tire (Quantity) ']) else 1
                cursor.execute("""
                    INSERT INTO transaction_items
                    (transaction_id, item_type, description, tire_size, quantity, unit_price, total_price, cost)
                    VALUES (?, 'new_tire', 'New Tire', ?, ?, ?, ?, ?)
                """, (transaction_id, tire_size, qty, new_tire/qty if qty > 0 else new_tire, new_tire, cost))
                stats['items'] += 1

            if alignment > 0:
                cursor.execute("""
                    INSERT INTO transaction_items
                    (transaction_id, item_type, description, quantity, unit_price, total_price)
                    VALUES (?, 'alignment', 'Alignment', 1, ?, ?)
                """, (transaction_id, alignment, alignment))
                stats['items'] += 1

            if other > 0:
                cursor.execute("""
                    INSERT INTO transaction_items
                    (transaction_id, item_type, description, quantity, unit_price, total_price, cost)
                    VALUES (?, 'other', 'Other Service', 1, ?, ?, ?)
                """, (transaction_id, other, other, cost if labor == 0 and used_tire == 0 and new_tire == 0 and alignment == 0 else 0))
                stats['items'] += 1

            # Commit every 500 rows
            if stats['transactions'] % 500 == 0:
                conn.commit()
                print(f"  Processed {stats['transactions']} transactions...")

        except Exception as e:
            print(f"Error on row {idx}: {e}")
            stats['skipped'] += 1

    conn.commit()
    conn.close()

    print(f"\nImport complete!")
    print(f"  Transactions: {stats['transactions']}")
    print(f"  Line items: {stats['items']}")
    print(f"  Skipped rows: {stats['skipped']}")


def verify_data():
    """Print summary of loaded data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\n=== Database Summary ===")

    cursor.execute("SELECT COUNT(*) FROM transactions")
    print(f"Total transactions: {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(*) FROM transaction_items")
    print(f"Total line items: {cursor.fetchone()[0]}")

    cursor.execute("""
        SELECT store_number, COUNT(*) as count, SUM(total) as revenue
        FROM transactions
        GROUP BY store_number
        ORDER BY store_number
    """)
    print("\nBy Store:")
    for row in cursor.fetchall():
        print(f"  Store #{row[0]}: {row[1]} transactions, ${row[2]:,.2f} revenue")

    cursor.execute("""
        SELECT item_type, COUNT(*) as count, SUM(total_price) as revenue
        FROM transaction_items
        GROUP BY item_type
        ORDER BY revenue DESC
    """)
    print("\nBy Item Type:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} items, ${row[2]:,.2f}")

    cursor.execute("""
        SELECT MIN(transaction_date) as min_date, MAX(transaction_date) as max_date
        FROM transactions
    """)
    dates = cursor.fetchone()
    print(f"\nDate range: {dates[0]} to {dates[1]}")

    conn.close()


if __name__ == "__main__":
    print("Jay's Tire Shop - Database Initialization")
    print("=" * 50)

    # Create database
    create_database()

    # Load historical data
    load_historical_data()

    # Verify
    verify_data()
