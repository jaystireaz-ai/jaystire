"""
Jay's Tire Shop - Backend API Server (PostgreSQL/Supabase)
Run with: gunicorn api:app
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import psycopg2.extras
from datetime import date, datetime
import os

app = Flask(__name__)
CORS(app)


def get_db():
    """Get PostgreSQL connection. Uses DATABASE_URL or individual DB_* env vars."""
    if os.environ.get('DATABASE_URL'):
        conn = psycopg2.connect(
            os.environ['DATABASE_URL'],
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    else:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'db.pqzyskwapuyjiqbufoqt.supabase.co'),
            port=int(os.environ.get('DB_PORT', 5432)),
            dbname=os.environ.get('DB_NAME', 'postgres'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD'),
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    return conn


def row_to_dict(row):
    """Convert a psycopg2 row to a plain dict, serializing dates to ISO strings."""
    if row is None:
        return None
    result = {}
    for key, val in row.items():
        if isinstance(val, (date, datetime)):
            result[key] = val.isoformat()
        else:
            result[key] = val
    return result


@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'database': 'supabase'})


@app.route('/api/transactions', methods=['POST'])
def create_transaction():
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO transactions
            (receipt_number, store_number, transaction_date, payment_method,
             subtotal, tax, total, cost, profit,
             vehicle_make, vehicle_model, vehicle_year, license_plate,
             employee_id, internal_notes, terminal_code, customer_phone, signature, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pos')
            RETURNING id
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

        transaction_id = cursor.fetchone()['id']

        for item in data.get('items', []):
            item_cost = item.get('cost', 0)
            from_inventory = 1 if item.get('from_inventory') else 0
            brand = item.get('brand')

            if from_inventory and item.get('item_type') == 'new_tire' and brand and item.get('tire_size'):
                cursor.execute("""
                    SELECT id, quantity, cost_per_tire FROM new_tire_inventory
                    WHERE store_number = %s AND brand = %s AND size = %s
                """, (data['store_number'], brand, item['tire_size']))
                inv_row = cursor.fetchone()
                if inv_row:
                    item_cost = (inv_row['cost_per_tire'] or 0) * item.get('quantity', 1)
                    new_qty = max(0, inv_row['quantity'] - item.get('quantity', 1))
                    cursor.execute("""
                        UPDATE new_tire_inventory SET quantity = %s, last_updated = NOW()
                        WHERE id = %s
                    """, (new_qty, inv_row['id']))

            cursor.execute("""
                INSERT INTO transaction_items
                (transaction_id, item_type, description, tire_size, tire_positions,
                 quantity, unit_price, total_price, cost, brand, from_inventory)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    try:
        conn = get_db()
        cursor = conn.cursor()

        query = "SELECT * FROM transactions WHERE 1=1"
        params = []

        if request.args.get('store'):
            query += " AND store_number = %s"
            params.append(int(request.args.get('store')))

        if request.args.get('date_from'):
            query += " AND transaction_date >= %s"
            params.append(request.args.get('date_from'))

        if request.args.get('date_to'):
            query += " AND transaction_date <= %s"
            params.append(request.args.get('date_to'))

        if request.args.get('license_plate'):
            query += " AND license_plate ILIKE %s"
            params.append(f"%{request.args.get('license_plate')}%")

        if request.args.get('receipt'):
            query += " AND receipt_number ILIKE %s"
            params.append(f"%{request.args.get('receipt')}%")

        if request.args.get('phone'):
            query += " AND customer_phone LIKE %s"
            params.append(f"%{request.args.get('phone')}%")

        if request.args.get('make'):
            query += " AND vehicle_make ILIKE %s"
            params.append(f"%{request.args.get('make')}%")

        if request.args.get('model'):
            query += " AND vehicle_model ILIKE %s"
            params.append(f"%{request.args.get('model')}%")

        if request.args.get('employee'):
            query += " AND employee_id = %s"
            params.append(request.args.get('employee'))

        if request.args.get('tire_size'):
            query += " AND id IN (SELECT transaction_id FROM transaction_items WHERE tire_size ILIKE %s)"
            params.append(f"%{request.args.get('tire_size')}%")

        if request.args.get('exclude_voided'):
            query += " AND (voided IS NULL OR voided = 0)"

        query += " ORDER BY transaction_date DESC, id DESC"

        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        query += f" LIMIT {limit} OFFSET {offset}"

        cursor.execute(query, params)
        transactions = [row_to_dict(row) for row in cursor.fetchall()]

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
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM transactions WHERE id = %s", (transaction_id,))
        transaction = row_to_dict(cursor.fetchone())

        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404

        cursor.execute("SELECT * FROM transaction_items WHERE transaction_id = %s", (transaction_id,))
        transaction['items'] = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({'success': True, 'transaction': transaction})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/transactions/by-receipt/<receipt_number>', methods=['GET'])
def get_transaction_by_receipt(receipt_number):
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM transactions WHERE receipt_number = %s", (receipt_number,))
        transaction = row_to_dict(cursor.fetchone())

        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404

        cursor.execute("SELECT * FROM transaction_items WHERE transaction_id = %s", (transaction['id'],))
        transaction['items'] = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({'success': True, 'transaction': transaction})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/transactions/<int:transaction_id>/void', methods=['POST'])
def void_transaction(transaction_id):
    try:
        data = request.get_json()
        voided_by = data.get('voided_by', '')
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM transactions WHERE id = %s", (transaction_id,))
        transaction = row_to_dict(cursor.fetchone())
        if not transaction:
            conn.close()
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        if transaction['voided']:
            conn.close()
            return jsonify({'success': False, 'error': 'Transaction is already voided'}), 400

        cursor.execute("SELECT * FROM transaction_items WHERE transaction_id = %s", (transaction_id,))
        items = cursor.fetchall()
        restored = []
        for item in items:
            if item['from_inventory'] and item['item_type'] == 'new_tire' and item['brand'] and item['tire_size']:
                cursor.execute("""
                    UPDATE new_tire_inventory SET quantity = quantity + %s, last_updated = NOW()
                    WHERE store_number = %s AND brand = %s AND size = %s
                """, (item['quantity'], transaction['store_number'], item['brand'], item['tire_size']))
                if cursor.rowcount > 0:
                    restored.append(f"{item['quantity']}x {item['brand']} {item['tire_size']}")

        cursor.execute("""
            UPDATE transactions SET voided = 1, voided_at = NOW(), voided_by = %s
            WHERE id = %s
        """, (voided_by, transaction_id))

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'restored_inventory': restored})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/stats', methods=['GET'])
def get_stats():
    try:
        conn = get_db()
        cursor = conn.cursor()

        where = "WHERE 1=1"
        params = []

        if request.args.get('store'):
            where += " AND store_number = %s"
            params.append(int(request.args.get('store')))

        if request.args.get('date_from'):
            where += " AND transaction_date >= %s"
            params.append(request.args.get('date_from'))

        if request.args.get('date_to'):
            where += " AND transaction_date <= %s"
            params.append(request.args.get('date_to'))

        cursor.execute(f"""
            SELECT
                COUNT(*) as total_transactions,
                SUM(total) as total_revenue,
                SUM(profit) as total_profit,
                AVG(total) as avg_transaction
            FROM transactions {where}
        """, params)
        overall = row_to_dict(cursor.fetchone())

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
        by_store = [row_to_dict(row) for row in cursor.fetchall()]

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
        by_type = [row_to_dict(row) for row in cursor.fetchall()]

        cursor.execute(f"""
            SELECT
                payment_method,
                COUNT(*) as transactions,
                SUM(total) as revenue
            FROM transactions {where}
            GROUP BY payment_method
        """, params)
        by_payment = [row_to_dict(row) for row in cursor.fetchall()]

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
    try:
        conn = get_db()
        cursor = conn.cursor()

        today = datetime.now().strftime("%m%d%y")
        prefix = f"{store_number}-{today}-"

        cursor.execute("""
            SELECT receipt_number FROM transactions
            WHERE receipt_number LIKE %s
            ORDER BY receipt_number DESC
            LIMIT 1
        """, (f"{prefix}%",))

        result = cursor.fetchone()
        conn.close()

        if result:
            last_num = result['receipt_number'].split('-')[-1]
            next_counter = int(last_num) + 1
        else:
            next_counter = 1

        next_receipt = f"{prefix}{next_counter:03d}"

        return jsonify({'success': True, 'receipt_number': next_receipt})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/import', methods=['POST'])
def import_transactions():
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'historical')
                RETURNING id
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

            transaction_id = cursor.fetchone()['id']

            for item in trans.get('items', []):
                cursor.execute("""
                    INSERT INTO transaction_items
                    (transaction_id, item_type, description, tire_size, quantity, unit_price, total_price, cost)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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

        return jsonify({'success': True, 'imported': imported})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    try:
        conn = get_db()
        cursor = conn.cursor()
        query = "SELECT * FROM new_tire_inventory WHERE quantity >= 0"
        params = []
        if request.args.get('store'):
            query += " AND store_number = %s"
            params.append(int(request.args.get('store')))
        query += " ORDER BY store_number, brand, size"
        cursor.execute(query, params)
        rows = [row_to_dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'inventory': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/receive', methods=['POST'])
def receive_inventory():
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
            WHERE store_number = %s AND brand = %s AND size = %s
        """, (store, brand, size))
        existing = cursor.fetchone()

        if existing:
            old_qty = existing['quantity']
            old_cost = existing['cost_per_tire'] or 0
            new_qty = old_qty + qty
            new_cost = ((old_qty * old_cost) + (qty * cost)) / new_qty if new_qty > 0 else cost
            if sale_price is not None:
                cursor.execute("""
                    UPDATE new_tire_inventory SET quantity = %s, cost_per_tire = %s, sale_price = %s, last_updated = NOW()
                    WHERE id = %s
                """, (new_qty, round(new_cost, 2), sale_price, existing['id']))
            else:
                cursor.execute("""
                    UPDATE new_tire_inventory SET quantity = %s, cost_per_tire = %s, last_updated = NOW()
                    WHERE id = %s
                """, (new_qty, round(new_cost, 2), existing['id']))
        else:
            cursor.execute("""
                INSERT INTO new_tire_inventory (store_number, brand, size, quantity, cost_per_tire, sale_price)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (store, brand, size, qty, cost, sale_price))

        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/transfer', methods=['POST'])
def transfer_inventory():
    try:
        data = request.get_json()
        from_store = int(data['from_store'])
        to_store = int(data['to_store'])
        brand = data['brand'].strip()
        size = data['size'].strip()
        qty = int(data['quantity'])

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, quantity, cost_per_tire, sale_price FROM new_tire_inventory
            WHERE store_number = %s AND brand = %s AND size = %s
        """, (from_store, brand, size))
        source = cursor.fetchone()

        if not source or source['quantity'] < qty:
            conn.close()
            available = source['quantity'] if source else 0
            return jsonify({'success': False, 'error': f'Not enough stock. Available: {available}'}), 400

        cost = source['cost_per_tire'] or 0
        sale_price = source['sale_price']

        cursor.execute("""
            UPDATE new_tire_inventory SET quantity = quantity - %s, last_updated = NOW()
            WHERE id = %s
        """, (qty, source['id']))

        cursor.execute("""
            SELECT id, quantity, cost_per_tire FROM new_tire_inventory
            WHERE store_number = %s AND brand = %s AND size = %s
        """, (to_store, brand, size))
        dest = cursor.fetchone()

        if dest:
            old_qty = dest['quantity']
            old_cost = dest['cost_per_tire'] or 0
            new_qty = old_qty + qty
            new_cost = ((old_qty * old_cost) + (qty * cost)) / new_qty if new_qty > 0 else cost
            cursor.execute("""
                UPDATE new_tire_inventory SET quantity = %s, cost_per_tire = %s, sale_price = COALESCE(sale_price, %s), last_updated = NOW()
                WHERE id = %s
            """, (new_qty, round(new_cost, 2), sale_price, dest['id']))
        else:
            cursor.execute("""
                INSERT INTO new_tire_inventory (store_number, brand, size, quantity, cost_per_tire, sale_price)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (to_store, brand, size, qty, cost, sale_price))

        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/pending-costs', methods=['GET'])
def get_pending_costs():
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
        rows = [row_to_dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'items': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/update-cost/<int:item_id>', methods=['POST'])
def update_item_cost(item_id):
    try:
        data = request.get_json()
        cost = float(data['cost'])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE transaction_items SET cost = %s WHERE id = %s", (cost, item_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/inventory/reconcile', methods=['POST'])
def submit_reconcile():
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

            cursor.execute("SELECT * FROM new_tire_inventory WHERE id = %s", (inv_id,))
            row = cursor.fetchone()
            if not row:
                continue

            system_qty = row['quantity']
            discrepancy = actual_qty - system_qty

            cursor.execute("""
                INSERT INTO inventory_adjustments
                (inventory_id, store_number, brand, size, system_qty, actual_qty, discrepancy, explanation, adjusted_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (inv_id, row['store_number'], row['brand'], row['size'],
                  system_qty, actual_qty, discrepancy, explanation, adjusted_by))

            cursor.execute("""
                UPDATE new_tire_inventory SET quantity = %s, last_updated = NOW() WHERE id = %s
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
        where += " AND t.store_number = %s"
        params.append(int(args.get('store')))
    if args.get('date_from'):
        where += " AND t.transaction_date >= %s"
        params.append(args.get('date_from'))
    if args.get('date_to'):
        where += " AND t.transaction_date <= %s"
        params.append(args.get('date_to'))
    return where, params


@app.route('/api/reports/summary', methods=['GET'])
def report_summary():
    try:
        where, params = report_filters(request.args)
        conn = get_db()
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) as txns, SUM(total) as revenue, AVG(total) as avg_sale FROM transactions t {where}", params)
        row = row_to_dict(c.fetchone())
        c.execute(f"SELECT store_number, SUM(total) as rev FROM transactions t {where} GROUP BY store_number ORDER BY rev DESC LIMIT 1", params)
        top = c.fetchone()
        conn.close()
        return jsonify({'success': True, 'data': {**row, 'top_store': row_to_dict(top) if top else None}})
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
        rows = [row_to_dict(r) for r in c.fetchall()]
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
        rows = [row_to_dict(r) for r in c.fetchall()]
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
        rows = [row_to_dict(r) for r in c.fetchall()]
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
        rows = [row_to_dict(r) for r in c.fetchall()]
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
            SELECT EXTRACT(DOW FROM transaction_date)::text as dow,
                   COUNT(*) as count, SUM(total) as revenue
            FROM transactions t {where}
            GROUP BY dow ORDER BY dow
        """, params)
        rows = [row_to_dict(r) for r in c.fetchall()]
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
            SELECT TO_CHAR(transaction_date, 'YYYY-MM') as month,
                   store_number, COUNT(*) as count, SUM(total) as revenue
            FROM transactions t {where}
            GROUP BY month, store_number ORDER BY month
        """, params)
        rows = [row_to_dict(r) for r in c.fetchall()]
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
            SELECT TO_CHAR(t.transaction_date, 'YYYY-MM') as month,
                   SUM(ti.cost) as total_cost, SUM(ti.total_price) as total_revenue,
                   COUNT(*) as count
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            {where} AND ti.item_type = 'new_tire'
            GROUP BY month ORDER BY month
        """, params)
        rows = [row_to_dict(r) for r in c.fetchall()]
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
            SELECT TO_CHAR(t.transaction_date, 'YYYY-MM') as month,
                   ti.brand, COUNT(*) as count
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            {where} AND ti.item_type = 'new_tire' AND ti.brand IS NOT NULL AND ti.brand != ''
            GROUP BY month, ti.brand ORDER BY month, count DESC
        """, params)
        rows = [row_to_dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("Jay's Tire Shop - API Server (Supabase/PostgreSQL)")
    print("=" * 50)
    print(f"Starting server on port {port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
