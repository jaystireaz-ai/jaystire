# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Jay's Tire Shop POS - A Point of Sale system for a 3-location tire shop business in Phoenix, AZ.

## Running the Application

1. **Start the API server** (required for database):
   ```bash
   python database/api.py
   ```
   Or double-click `start_server.bat`

2. **Open the POS**: Open `index.html` in a browser, or serve via HTTP server

The API runs on `http://localhost:5000`. The POS will still work without the API (for offline use) but transactions won't be saved to the database.

## Architecture

**Frontend:**
- `index.html` - Dashboard landing page with store selection
- `pos.html` - Full POS system as a single React component (React 18 + Babel via CDN)

**Backend:**
- `database/api.py` - Flask REST API for transaction storage
- `database/jaystire.db` - SQLite database with all transactions
- `database/init_db.py` - Database initialization and historical data import

**API Endpoints:**
- `POST /api/transactions` - Create new transaction
- `GET /api/transactions` - Query transactions (filters: store, date_from, date_to, license_plate, receipt)
- `GET /api/transactions/<id>` - Get single transaction with items
- `GET /api/stats` - Get summary statistics

## Database Schema

**transactions** - One row per sale:
- receipt_number, store_number, transaction_date, payment_method
- subtotal, tax, total, cost, profit
- vehicle_make, vehicle_model, vehicle_year, license_plate
- employee_id, internal_notes, terminal_code
- source ('pos' or 'historical')

**transaction_items** - Line items for each transaction:
- item_type: 'used_tire', 'new_tire', 'labor', 'alignment', 'other'
- tire_size, tire_positions, quantity, unit_price, total_price

## Key Business Logic

- **Tax:** 8.6% applied only to card payments, not cash
- **Receipt numbering:** Format `[store]-[MMDDYY]-[###]`
- **Tire positions:** LF, RF, LR, RR, S (spare)
- **Employee IDs:** Hardcoded as Employee #1, #2, #3

## BI Tool Integration

Connect Tableau or Power BI directly to `database/jaystire.db` (SQLite). New transactions appear immediately on refresh.
