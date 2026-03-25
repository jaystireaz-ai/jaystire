"""
Jay's Tire Shop - Backend API Server
Run with: python api.py
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
from pathlib import Path
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)  # Allow requests from POS frontend (including Netlify)

# Database path - use /data for Railway persistent storage, or local for development
if os.environ.get('RAILWAY_ENVIRONMENT'):
    DB_PATH = Path("/data/jaystire.db")
else:
    DB_PATH = Path(__file__).parent / "jaystire.db"


def init_db():
    """Initialize database tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

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
            vehicle_make TEXT,
            vehicle_model TEXT,
            vehicle_year INTEGER,
            license_plate TEXT,
            employee_id TEXT,
            internal_notes TEXT,
            terminal_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'pos'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            description TEXT,
            tire_size TEXT,
            tire_positions TEXT,
            quantity INTEGER DEFAULT 1,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            cost REAL DEFAULT 0,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_store ON transactions(store_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_receipt ON transactions(receipt_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_plate ON transactions(license_plate)")

    # New tire inventory table
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

    # Add new columns to transaction_items for existing databases
    for col_sql in [
        "ALTER TABLE transaction_items ADD COLUMN brand TEXT",
        "ALTER TABLE transaction_items ADD COLUMN from_inventory INTEGER DEFAULT 0"
    ]:
        try:
            cursor.execute(col_sql)
        except Exception:
            pass  # Column already exists

    # Add sale_price to inventory if not present
    try:
        cursor.execute("ALTER TABLE new_tire_inventory ADD COLUMN sale_price REAL")
    except Exception:
        pass

    # Add customer_phone to transactions if not present
    try:
        cursor.execute("ALTER TABLE transactions ADD COLUMN customer_phone TEXT")
    except Exception:
        pass

    # Add void + signature support to transactions
    for col_sql in [
        "ALTER TABLE transactions ADD COLUMN voided INTEGER DEFAULT 0",
        "ALTER TABLE transactions ADD COLUMN voided_at TIMESTAMP",
        "ALTER TABLE transactions ADD COLUMN voided_by TEXT",
        "ALTER TABLE transactions ADD COLUMN signature TEXT",
    ]:
        try:
            cursor.execute(col_sql)
        except Exception:
            pass

    # Inventory reconciliation audit trail
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id INTEGER NOT NULL,
            store_number INTEGER NOT NULL,
            brand TEXT NOT NULL,
            size TEXT NOT NULL,
            system_qty INTEGER NOT NULL,
            actual_qty INTEGER NOT NULL,
            discrepancy INTEGER NOT NULL,
            explanation TEXT,
            adjusted_by TEXT,
            adjusted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn


# Initialize database on startup
init_db()


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'database': str(DB_PATH)})


@app.route('/api/transactions', methods=['POST'])
def create_transaction():
    """
    Create a new transaction with line items.

    Expected JSON format:
    {
        "receipt_number": "1-011826-001",
        "store_number": 1,
        "transaction_date": "2026-01-18",
        "payment_method": "Cash",
        "subtotal": 100.00,
        "tax": 0,
        "total": 100.00,
        "vehicle_make": "Honda",
        "vehicle_model": "Accord",
        "vehicle_year": 2020,
        "license_plate": "ABC123",
        "employee_id": "Employee #1",
        "internal_notes": "Customer notes here",
        "terminal_code": null,
        "items": [
            {
                "item_type": "used_tire",
                "description": "Used Tire",
                "tire_size": "265/75/16",
                "tire_positions": "LF,RF",
                "quantity": 2,
                "unit_price": 50.00,
                "total_price": 100.00
            }
        ]
    }
    """
    try:
        data = request.get_json()

        conn = get_db()
        cursor = conn.cursor()

        # Insert transaction
        cursor.execute("""
            INSERT INTO transactions
            (receipt_number, store_number, transaction_date, payment_method,
             subtotal, tax, total, cost, profit,
             vehicle_make, vehicle_model, vehicle_year, license_plate,
             employee_id, internal_notes, terminal_code, customer_phone, signature, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pos')
        """, (
            data['receipt_number'],
            data['store_number'],
            data['transaction_date'],
            data['payment_method'],
            data.get('subtotal', 0),
            data.get('tax', 0),
            data.get('total', 0),
            data.get('cost', 0),
            data.get('profit', data.get('total', 0) - data.get('cost', 0)),
            data.get('vehicle_make'),
            data.get('vehicle_model'),
            data.get('vehicle_year'),
            data.get('license_plate'),
            data.get('employee_id'),
            data.get('internal_notes'),
            data.get('terminal_code'),
            data.get('customer_phone'),
            data.get('signature')
        ))

        transaction_id = cursor.lastrowid

        # Insert line items
        for item in data.get('items', []):
            item_cost = item.get('cost', 0)
            from_inventory = 1 if item.get('from_inventory') else 0
            brand = item.get('brand')

            # If sold from inventory: deduct stock and pull cost
            if from_inventory and item.get('item_type') == 'new_tire' and brand and item.get('tire_size'):
                cursor.execute("""
                    SELECT id, quantity, cost_per_tire FROM new_tire_inventory
                    WHERE store_number = ? AND brand = ? AND size = ?
                """, (data['store_number'], brand, item['tire_size']))
                inv_row = cursor.fetchone()
                if inv_row:
                    item_cost = (inv_row['cost_per_tire'] or 0) * item.get('quantity', 1)
                    new_qty = max(0, inv_row['quantity'] - item.get('quantity', 1))
                    cursor.execute("""
                        UPDATE new_tire_inventory SET quantity = ?, last_updated = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (new_qty, inv_row['id']))

            cursor.execute("""
                INSERT INTO transaction_items
                (transaction_id, item_type, description, tire_size, tire_positions,
                 quantity, unit_price, total_price, cost, brand, from_inventory)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction_id,
                item['item_type'],
                item.get('description', ''),
                item.get('tire_size'),
                item.get('tire_positions'),
                item.get('quantity', 1),
                item['unit_price'],
                item['total_price'],
                item_cost,
                brand,
                from_inventory
            ))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'transaction_id': transaction_id,
            'receipt_number': data['receipt_number']
        }), 201

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    """
    Get transactions with optional filters.

    Query parameters:
    - store: filter by store number (1, 2, 3)
    - date_from: start date (YYYY-MM-DD)
    - date_to: end date (YYYY-MM-DD)
    - license_plate: search by license plate
    - receipt: search by receipt number
    - limit: max results (default 100)
    - offset: pagination offset (default 0)
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Build query with filters
        query = "SELECT * FROM transactions WHERE 1=1"
        params = []

        if request.args.get('store'):
            query += " AND store_number = ?"
            params.append(int(request.args.get('store')))

        if request.args.get('date_from'):
            query += " AND transaction_date >= ?"
            params.append(request.args.get('date_from'))

        if request.args.get('date_to'):
            query += " AND transaction_date <= ?"
            params.append(request.args.get('date_to'))

        if request.args.get('license_plate'):
            query += " AND license_plate LIKE ?"
            params.append(f"%{request.args.get('license_plate')}%")

        if request.args.get('receipt'):
            query += " AND receipt_number LIKE ?"
            params.append(f"%{request.args.get('receipt')}%")

        if request.args.get('phone'):
            query += " AND customer_phone LIKE ?"
            params.append(f"%{request.args.get('phone')}%")

        if request.args.get('make'):
            query += " AND vehicle_make LIKE ?"
            params.append(f"%{request.args.get('make')}%")

        if request.args.get('model'):
            query += " AND vehicle_model LIKE ?"
            params.append(f"%{request.args.get('model')}%")

        if request.args.get('employee'):
            query += " AND employee_id = ?"
            params.append(request.args.get('employee'))

        if request.args.get('tire_size'):
            query += " AND id IN (SELECT transaction_id FROM transaction_items WHERE tire_size LIKE ?)"
            params.append(f"%{request.args.get('tire_size')}%")

        # Exclude voided only for void tab (which passes exclude_voided=1)
        if request.args.get('exclude_voided'):
            query += " AND (voided IS NULL OR voided = 0)"

        query += " ORDER BY transaction_date DESC, id DESC"

        # Pagination
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        query += f" LIMIT {limit} OFFSET {offset}"

        cursor.execute(query, params)
        transactions = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({
            'success': True,
            'count': len(transactions),
            'transactions': transactions
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/transactions/<int:transaction_id>', methods=['GET'])
def get_transaction(transaction_id):
    """Get a single transaction with its line items."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get transaction
        cursor.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,))
        transaction = cursor.fetchone()

        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404

        transaction = dict(transaction)

        # Get line items
        cursor.execute("SELECT * FROM transaction_items WHERE transaction_id = ?", (transaction_id,))
        transaction['items'] = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({
            'success': True,
            'transaction': transaction
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/transactions/by-receipt/<receipt_number>', methods=['GET'])
def get_transaction_by_receipt(receipt_number):
    """Get a transaction by receipt number."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM transactions WHERE receipt_number = ?", (receipt_number,))
        transaction = cursor.fetchone()

        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404

        transaction = dict(transaction)

        cursor.execute("SELECT * FROM transaction_items WHERE transaction_id = ?", (transaction['id'],))
        transaction['items'] = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({
            'success': True,
            'transaction': transaction
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/transactions/<int:transaction_id>/void', methods=['POST'])
def void_transaction(transaction_id):
    """Void a transaction and restore any inventory that was decremented."""
    try:
        data = request.get_json()
        voided_by = data.get('voided_by', '')
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,))
        transaction = cursor.fetchone()
        if not transaction:
            conn.close()
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        if transaction['voided']:
            conn.close()
            return jsonify({'success': False, 'error': 'Transaction is already voided'}), 400

        # Restore inventory for items sold from stock
        cursor.execute("SELECT * FROM transaction_items WHERE transaction_id = ?", (transaction_id,))
        items = cursor.fetchall()
        restored = []
        for item in items:
            if item['from_inventory'] and item['item_type'] == 'new_tire' and item['brand'] and item['tire_size']:
                cursor.execute("""
                    UPDATE new_tire_inventory SET quantity = quantity + ?, last_updated = CURRENT_TIMESTAMP
                    WHERE store_number = ? AND brand = ? AND size = ?
                """, (item['quantity'], transaction['store_number'], item['brand'], item['tire_size']))
                if cursor.rowcount > 0:
                    restored.append(f"{item['quantity']}x {item['brand']} {item['tire_size']}")

        cursor.execute("""
            UPDATE transactions SET voided = 1, voided_at = CURRENT_TIMESTAMP, voided_by = ?
            WHERE id = ?
        """, (voided_by, transaction_id))

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'restored_inventory': restored})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get summary statistics, optionally filtered by store and date range."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Build filter
        where = "WHERE 1=1"
        params = []

        if request.args.get('store'):
            where += " AND store_number = ?"
            params.append(int(request.args.get('store')))

        if request.args.get('date_from'):
            where += " AND transaction_date >= ?"
            params.append(request.args.get('date_from'))

        if request.args.get('date_to'):
            where += " AND transaction_date <= ?"
            params.append(request.args.get('date_to'))

        # Overall stats
        cursor.execute(f"""
            SELECT
                COUNT(*) as total_transactions,
                SUM(total) as total_revenue,
                SUM(profit) as total_profit,
                AVG(total) as avg_transaction
            FROM transactions {where}
        """, params)
        overall = dict(cursor.fetchone())

        # By store
        cursor.execute(f"""
            SELECT
                store_number,
                COUNT(*) as transactions,
                SUM(total) as revenue,
                SUM(profit) as profit
            FROM transactions {where}
            GROUP BY store_number
            ORDER BY store_number
        """, params)
        by_store = [dict(row) for row in cursor.fetchall()]

        # By item type
        cursor.execute(f"""
            SELECT
                ti.item_type,
                COUNT(*) as count,
                SUM(ti.total_price) as revenue
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            {where}
            GROUP BY ti.item_type
            ORDER BY revenue DESC
        """, params)
        by_type = [dict(row) for row in cursor.fetchall()]

        # By payment method
        cursor.execute(f"""
            SELECT
                payment_method,
                COUNT(*) as transactions,
                SUM(total) as revenue
            FROM transactions {where}
            GROUP BY payment_method
        """, params)
        by_payment = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({
            'success': True,
            'overall': overall,
            'by_store': by_store,
            'by_item_type': by_type,
            'by_payment_method': by_payment
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/next-receipt-number/<int:store_number>', methods=['GET'])
def get_next_receipt_number(store_number):
    """Get the next receipt number for a store."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        today = datetime.now().strftime("%m%d%y")
        prefix = f"{store_number}-{today}-"

        # Find highest receipt number for this store and date
        cursor.execute("""
            SELECT receipt_number FROM transactions
            WHERE receipt_number LIKE ?
            ORDER BY receipt_number DESC
            LIMIT 1
        """, (f"{prefix}%",))

        result = cursor.fetchone()
        conn.close()

        if result:
            # Extract counter and increment
            last_num = result[0].split('-')[-1]
            next_counter = int(last_num) + 1
        else:
            next_counter = 1

        next_receipt = f"{prefix}{next_counter:03d}"

        return jsonify({
            'success': True,
            'receipt_number': next_receipt
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/import', methods=['POST'])
def import_transactions():
    """
    Bulk import transactions (for loading historical data).
    Expects JSON array of transaction objects.
    """
    try:
        data = request.get_json()
        transactions = data.get('transactions', [])

        conn = get_db()
        cursor = conn.cursor()

        imported = 0
        for trans in transactions:
            cursor.execute("""
                INSERT INTO transactions
                (receipt_number, store_number, transaction_date, payment_method,
                 subtotal, tax, total, cost, profit, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'historical')
            """, (
                trans['receipt_number'],
                trans['store_number'],
                trans['transaction_date'],
                trans['payment_method'],
                trans.get('subtotal', trans.get('total', 0)),
                trans.get('tax', 0),
                trans.get('total', 0),
                trans.get('cost', 0),
                trans.get('profit', 0)
            ))

            transaction_id = cursor.lastrowid

            for item in trans.get('items', []):
                cursor.execute("""
                    INSERT INTO transaction_items
                    (transaction_id, item_type, description, tire_size, quantity, unit_price, total_price, cost)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    transaction_id,
                    item['item_type'],
                    item.get('description', ''),
                    item.get('tire_size'),
                    item.get('quantity', 1),
                    item.get('unit_price', item.get('total_price', 0)),
                    item.get('total_price', 0),
                    item.get('cost', 0)
                ))

            imported += 1

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'imported': imported
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    """Get new tire inventory, optionally filtered by store."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        query = "SELECT * FROM new_tire_inventory WHERE quantity >= 0"
        params = []
        if request.args.get('store'):
            query += " AND store_number = ?"
            params.append(int(request.args.get('store')))
        query += " ORDER BY store_number, brand, size"
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'inventory': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/receive', methods=['POST'])
def receive_inventory():
    """Add or update stock for a store. Weighted average cost if already exists."""
    try:
        data = request.get_json()
        store = int(data['store_number'])
        brand = data['brand'].strip()
        size = data['size'].strip()
        qty = int(data['quantity'])
        cost = float(data['cost_per_tire'])
        sale_price = float(data['sale_price']) if data.get('sale_price') else None

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, quantity, cost_per_tire FROM new_tire_inventory
            WHERE store_number = ? AND brand = ? AND size = ?
        """, (store, brand, size))
        existing = cursor.fetchone()

        if existing:
            old_qty = existing['quantity']
            old_cost = existing['cost_per_tire'] or 0
            new_qty = old_qty + qty
            new_cost = ((old_qty * old_cost) + (qty * cost)) / new_qty if new_qty > 0 else cost
            if sale_price is not None:
                cursor.execute("""
                    UPDATE new_tire_inventory SET quantity = ?, cost_per_tire = ?, sale_price = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_qty, round(new_cost, 2), sale_price, existing['id']))
            else:
                cursor.execute("""
                    UPDATE new_tire_inventory SET quantity = ?, cost_per_tire = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_qty, round(new_cost, 2), existing['id']))
        else:
            cursor.execute("""
                INSERT INTO new_tire_inventory (store_number, brand, size, quantity, cost_per_tire, sale_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (store, brand, size, qty, cost, sale_price))

        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/transfer', methods=['POST'])
def transfer_inventory():
    """Transfer tires from one store to another."""
    try:
        data = request.get_json()
        from_store = int(data['from_store'])
        to_store = int(data['to_store'])
        brand = data['brand'].strip()
        size = data['size'].strip()
        qty = int(data['quantity'])

        conn = get_db()
        cursor = conn.cursor()

        # Get source inventory
        cursor.execute("""
            SELECT id, quantity, cost_per_tire, sale_price FROM new_tire_inventory
            WHERE store_number = ? AND brand = ? AND size = ?
        """, (from_store, brand, size))
        source = cursor.fetchone()

        if not source or source['quantity'] < qty:
            conn.close()
            available = source['quantity'] if source else 0
            return jsonify({'success': False, 'error': f'Not enough stock. Available: {available}'}), 400

        cost = source['cost_per_tire'] or 0
        sale_price = source['sale_price']

        # Deduct from source
        cursor.execute("""
            UPDATE new_tire_inventory SET quantity = quantity - ?, last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (qty, source['id']))

        # Add to destination (weighted avg cost if exists, carry sale_price)
        cursor.execute("""
            SELECT id, quantity, cost_per_tire FROM new_tire_inventory
            WHERE store_number = ? AND brand = ? AND size = ?
        """, (to_store, brand, size))
        dest = cursor.fetchone()

        if dest:
            old_qty = dest['quantity']
            old_cost = dest['cost_per_tire'] or 0
            new_qty = old_qty + qty
            new_cost = ((old_qty * old_cost) + (qty * cost)) / new_qty if new_qty > 0 else cost
            cursor.execute("""
                UPDATE new_tire_inventory SET quantity = ?, cost_per_tire = ?, sale_price = COALESCE(sale_price, ?), last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_qty, round(new_cost, 2), sale_price, dest['id']))
        else:
            cursor.execute("""
                INSERT INTO new_tire_inventory (store_number, brand, size, quantity, cost_per_tire, sale_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (to_store, brand, size, qty, cost, sale_price))

        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/pending-costs', methods=['GET'])
def get_pending_costs():
    """Get new tire special-order sales with no cost recorded yet."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ti.id, ti.description, ti.brand, ti.tire_size, ti.quantity,
                   ti.unit_price, ti.total_price,
                   t.transaction_date, t.receipt_number, t.store_number
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            WHERE ti.item_type = 'new_tire'
              AND ti.from_inventory = 0
              AND (ti.cost IS NULL OR ti.cost = 0)
              AND t.source = 'pos'
            ORDER BY t.transaction_date DESC, t.id DESC
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'items': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/update-cost/<int:item_id>', methods=['POST'])
def update_item_cost(item_id):
    """Update cost on a transaction item (for special orders entered after the fact)."""
    try:
        data = request.get_json()
        cost = float(data['cost'])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE transaction_items SET cost = ? WHERE id = ?", (cost, item_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/reconcile', methods=['POST'])
def submit_reconcile():
    """Submit weekly inventory reconciliation — saves adjustments and updates quantities."""
    try:
        data = request.get_json()
        adjustments = data.get('adjustments', [])
        adjusted_by = data.get('adjusted_by', '')

        conn = get_db()
        cursor = conn.cursor()

        for adj in adjustments:
            inv_id = adj['id']
            actual_qty = int(adj['actual_qty'])
            explanation = adj.get('explanation', '')

            cursor.execute("SELECT * FROM new_tire_inventory WHERE id = ?", (inv_id,))
            row = cursor.fetchone()
            if not row:
                continue

            system_qty = row['quantity']
            discrepancy = actual_qty - system_qty

            cursor.execute("""
                INSERT INTO inventory_adjustments
                (inventory_id, store_number, brand, size, system_qty, actual_qty, discrepancy, explanation, adjusted_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (inv_id, row['store_number'], row['brand'], row['size'],
                  system_qty, actual_qty, discrepancy, explanation, adjusted_by))

            cursor.execute("""
                UPDATE new_tire_inventory SET quantity = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?
            """, (actual_qty, inv_id))

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'adjusted': len(adjustments)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


def report_filters(args):
    """Build WHERE clause and params for common report filters."""
    where = "WHERE (t.voided IS NULL OR t.voided = 0)"
    params = []
    if args.get('store'):
        where += " AND t.store_number = ?"
        params.append(int(args.get('store')))
    if args.get('date_from'):
        where += " AND t.transaction_date >= ?"
        params.append(args.get('date_from'))
    if args.get('date_to'):
        where += " AND t.transaction_date <= ?"
        params.append(args.get('date_to'))
    return where, params


@app.route('/api/reports/summary', methods=['GET'])
def report_summary():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) as txns, SUM(total) as revenue, AVG(total) as avg_sale FROM transactions t {where}", params)
        row = dict(c.fetchone())
        c.execute(f"SELECT store_number, SUM(total) as rev FROM transactions t {where} GROUP BY store_number ORDER BY rev DESC LIMIT 1", params)
        top = c.fetchone()
        conn.close()
        return jsonify({'success': True, 'data': {**row, 'top_store': dict(top) if top else None}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/payment-methods', methods=['GET'])
def report_payment_methods():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT
                CASE
                    WHEN LOWER(payment_method) LIKE '%card%' AND LOWER(payment_method) LIKE '%cash%' THEN 'Cash + Card'
                    WHEN LOWER(payment_method) LIKE '%card%' THEN 'Card'
                    ELSE 'Cash'
                END as method,
                COUNT(*) as count, SUM(total) as revenue
            FROM transactions t {where}
            GROUP BY method ORDER BY revenue DESC
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/daily-sales', methods=['GET'])
def report_daily_sales():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT transaction_date, store_number, COUNT(*) as count, SUM(total) as revenue
            FROM transactions t {where}
            GROUP BY transaction_date, store_number
            ORDER BY transaction_date
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/service-breakdown', methods=['GET'])
def report_service_breakdown():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT ti.item_type, COUNT(*) as count, SUM(ti.total_price) as revenue
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            {where}
            GROUP BY ti.item_type ORDER BY revenue DESC
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/tire-sizes', methods=['GET'])
def report_tire_sizes():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT ti.tire_size, COUNT(*) as count
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            {where}
            AND ti.item_type IN ('used_tire','new_tire')
            AND ti.tire_size IS NOT NULL AND ti.tire_size != ''
            GROUP BY ti.tire_size ORDER BY count DESC LIMIT 20
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/day-of-week', methods=['GET'])
def report_day_of_week():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT strftime('%w', transaction_date) as dow,
                   COUNT(*) as count, SUM(total) as revenue
            FROM transactions t {where}
            GROUP BY dow ORDER BY dow
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/monthly-revenue', methods=['GET'])
def report_monthly_revenue():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT strftime('%Y-%m', transaction_date) as month,
                   store_number, COUNT(*) as count, SUM(total) as revenue
            FROM transactions t {where}
            GROUP BY month, store_number ORDER BY month
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/monthly-tire-cost', methods=['GET'])
def report_monthly_tire_cost():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT strftime('%Y-%m', t.transaction_date) as month,
                   SUM(ti.cost) as total_cost, SUM(ti.total_price) as total_revenue,
                   COUNT(*) as count
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            {where} AND ti.item_type = 'new_tire'
            GROUP BY month ORDER BY month
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/monthly-brands', methods=['GET'])
def report_monthly_brands():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"""
            SELECT strftime('%Y-%m', t.transaction_date) as month,
                   ti.brand, COUNT(*) as count
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            {where} AND ti.item_type = 'new_tire' AND ti.brand IS NOT NULL AND ti.brand != ''
            GROUP BY month, ti.brand ORDER BY month, count DESC
        """, params)
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = not os.environ.get('RAILWAY_ENVIRONMENT')
    print("=" * 50)
    print("Jay's Tire Shop - API Server")
    print("=" * 50)
    print(f"Database: {DB_PATH}")
    print(f"Starting server on port {port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=debug)
