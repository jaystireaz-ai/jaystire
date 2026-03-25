"""
Upload historical data from local database to Railway.
Run this AFTER deploying to Railway.

Usage: python upload_to_railway.py https://your-railway-url.railway.app
"""
import sqlite3
import requests
import json
import sys
from pathlib import Path

LOCAL_DB = Path(__file__).parent / "jaystire.db"
BATCH_SIZE = 100  # Upload in batches to avoid timeout


def export_and_upload(railway_url):
    """Export local data and upload to Railway."""

    # Remove trailing slash if present
    railway_url = railway_url.rstrip('/')

    print(f"Connecting to local database: {LOCAL_DB}")
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all transactions
    cursor.execute("SELECT * FROM transactions ORDER BY id")
    transactions = [dict(row) for row in cursor.fetchall()]
    print(f"Found {len(transactions)} transactions to upload")

    # Get all items
    cursor.execute("SELECT * FROM transaction_items ORDER BY transaction_id")
    all_items = [dict(row) for row in cursor.fetchall()]

    # Group items by transaction_id
    items_by_trans = {}
    for item in all_items:
        tid = item['transaction_id']
        if tid not in items_by_trans:
            items_by_trans[tid] = []
        items_by_trans[tid].append(item)

    conn.close()

    # Prepare transactions with their items
    upload_data = []
    for trans in transactions:
        trans_id = trans['id']
        trans['items'] = items_by_trans.get(trans_id, [])
        # Remove local id fields (Railway will generate new ones)
        del trans['id']
        if 'created_at' in trans:
            del trans['created_at']
        for item in trans['items']:
            del item['id']
            del item['transaction_id']
        upload_data.append(trans)

    # Upload in batches
    total_uploaded = 0
    for i in range(0, len(upload_data), BATCH_SIZE):
        batch = upload_data[i:i+BATCH_SIZE]
        print(f"Uploading batch {i//BATCH_SIZE + 1} ({len(batch)} transactions)...")

        response = requests.post(
            f"{railway_url}/api/import",
            json={"transactions": batch},
            headers={"Content-Type": "application/json"},
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            total_uploaded += result.get('imported', 0)
            print(f"  Uploaded {result.get('imported', 0)} transactions")
        else:
            print(f"  Error: {response.status_code} - {response.text}")
            return

    print(f"\nDone! Total uploaded: {total_uploaded} transactions")

    # Verify
    print("\nVerifying upload...")
    response = requests.get(f"{railway_url}/api/stats")
    if response.status_code == 200:
        stats = response.json()
        print(f"Railway database now has {stats['overall']['total_transactions']} transactions")
        print(f"Total revenue: ${stats['overall']['total_revenue']:,.2f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_to_railway.py https://your-app.railway.app")
        print("\nExample: python upload_to_railway.py https://jaystire-api.up.railway.app")
        sys.exit(1)

    railway_url = sys.argv[1]
    print(f"Uploading to: {railway_url}")
    export_and_upload(railway_url)
