from flask import Flask, render_template, request, redirect, send_file
import sqlite3
from fpdf import FPDF
from datetime import datetime
import os

app = Flask(__name__)

# ---------------- HELPER ----------------
def safe_text(text):
    if text is None:
        return ""
    return str(text).encode("latin-1", "ignore").decode("latin-1")

def amount_in_words(amount):
    try:
        from num2words import num2words
        words = num2words(amount, lang='en_IN').title()
        return safe_text(words + " Only")
    except:
        return ""

# ---------------- DB ----------------
def get_db():
    conn = sqlite3.connect("invoice.db")
    conn.row_factory = sqlite3.Row   # ✅ CRITICAL FIX
    return conn

def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS sellers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, state TEXT, address TEXT, gst TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS receivers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, state TEXT, address TEXT, gst TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, hsn TEXT, unit TEXT, gst_rate REAL
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT,
        date TEXT,
        seller_id INTEGER,
        receiver_id INTEGER,
        taxable REAL,
        cgst REAL,
        sgst REAL,
        igst REAL,
        total REAL
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS invoice_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        product_id INTEGER,
        rate REAL,
        qty REAL,
        discount REAL,
        taxable REAL,
        cgst REAL,
        sgst REAL,
        igst REAL
    )""")

    db.commit()
    db.close()

init_db()

# ---------------- DASHBOARD ----------------
@app.route("/")
def dashboard():
    db = get_db()
    invoices = db.execute("SELECT * FROM invoices").fetchall()
    db.close()
    return render_template("dashboard.html", invoices=invoices)

# ---------------- SELLER ----------------
@app.route("/seller", methods=["GET", "POST"])
def seller():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO sellers(name,state,address,gst) VALUES(?,?,?,?)",
                   (request.form.get("name",""),
                    request.form.get("state",""),
                    request.form.get("address",""),
                    request.form.get("gst","")))
        db.commit()

    sellers = db.execute("SELECT * FROM sellers").fetchall()
    db.close()
    return render_template("seller.html", sellers=sellers)

@app.route("/delete_seller/<int:id>")
def delete_seller(id):
    db = get_db()
    db.execute("DELETE FROM sellers WHERE id=?", (id,))
    db.commit()
    db.close()
    return redirect("/seller")

# ---------------- RECEIVER ----------------
@app.route("/receiver", methods=["GET","POST"])
def receiver():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO receivers(name,state,address,gst) VALUES(?,?,?,?)",
                   (request.form.get("name",""),
                    request.form.get("state",""),
                    request.form.get("address",""),
                    request.form.get("gst","")))
        db.commit()

    receivers = db.execute("SELECT * FROM receivers").fetchall()
    db.close()
    return render_template("receiver.html", receivers=receivers)

@app.route("/delete_receiver/<int:id>")
def delete_receiver(id):
    db = get_db()
    db.execute("DELETE FROM receivers WHERE id=?", (id,))
    db.commit()
    db.close()
    return redirect("/receiver")

# ---------------- PRODUCT ----------------
@app.route("/product", methods=["GET","POST"])
def product():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO products(name,hsn,unit,gst_rate) VALUES(?,?,?,?)",
                   (request.form.get("name",""),
                    request.form.get("hsn",""),
                    request.form.get("unit",""),
                    float(request.form.get("gst_rate",0))))
        db.commit()

    products = db.execute("SELECT * FROM products").fetchall()
    db.close()
    return render_template("product.html", products=products)

@app.route("/delete_product/<int:id>")
def delete_product(id):
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (id,))
    db.commit()
    db.close()
    return redirect("/product")

# ---------------- INVOICE ----------------
@app.route("/invoice", methods=["GET", "POST"])
def invoice():
    db = get_db()

    sellers = db.execute("SELECT id, name FROM sellers").fetchall()
    receivers = db.execute("SELECT id, name FROM receivers").fetchall()
    products = db.execute("SELECT id, name, gst_rate FROM products").fetchall()

    if request.method == "POST":

        invoice_no = request.form.get("invoice_no") or \
            f"AUTO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        invoice_date = request.form.get("invoice_date")

        seller_id = request.form["seller_id"]
        receiver_id = request.form["receiver_id"]

        seller_state = db.execute(
            "SELECT state FROM sellers WHERE id=?", (seller_id,)
        ).fetchone()["state"]

        receiver_state = db.execute(
            "SELECT state FROM receivers WHERE id=?", (receiver_id,)
        ).fetchone()["state"]

        same_state = seller_state == receiver_state

        cur = db.cursor()
        cur.execute("""
            INSERT INTO invoices (
                invoice_no, date, seller_id, receiver_id,
                taxable, cgst, sgst, igst, total
            ) VALUES (?,?,?,?,0,0,0,0,0)
        """, (
            invoice_no,
            datetime.strptime(invoice_date, "%Y-%m-%d").strftime("%d-%m-%Y"),
            seller_id,
            receiver_id
        ))

        invoice_id = cur.lastrowid

        total_taxable = total_cgst = total_sgst = total_igst = 0

        product_ids = request.form.getlist("product_id[]")
        rates = request.form.getlist("rate[]")
        qtys = request.form.getlist("qty[]")
        discounts = request.form.getlist("discount[]")

        for i in range(len(product_ids)):
            rate = float(rates[i] or 0)
            qty = float(qtys[i] or 0)
            discount = float(discounts[i] or 0)

            if rate == 0 or qty == 0:
                continue

            taxable = (rate * qty) - discount
            gst_rate = db.execute(
                "SELECT gst_rate FROM products WHERE id=?",
                (product_ids[i],)
            ).fetchone()["gst_rate"]

            gst = taxable * gst_rate / 100

            if same_state:
                cgst = sgst = gst / 2
                igst = 0
            else:
                cgst = sgst = 0
                igst = gst

            total_taxable += taxable
            total_cgst += cgst
            total_sgst += sgst
            total_igst += igst

            cur.execute("""
                INSERT INTO invoice_items
                (invoice_id, product_id, rate, qty, discount,
                 taxable, cgst, sgst, igst)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                invoice_id, product_ids[i], rate, qty, discount,
                taxable, cgst, sgst, igst
            ))

        total_invoice = total_taxable + total_cgst + total_sgst + total_igst

        cur.execute("""
            UPDATE invoices
            SET taxable=?, cgst=?, sgst=?, igst=?, total=?
            WHERE id=?
        """, (
            total_taxable, total_cgst, total_sgst,
            total_igst, total_invoice, invoice_id
        ))

        db.commit()
        db.close()
        return redirect("/")

    db.close()
    return render_template(
        "invoice.html",
        sellers=sellers,
        receivers=receivers,
        products=products
    )

# ---------------- PDF ----------------
@app.route("/pdf/<int:id>")
def pdf(id):
    db = get_db()
    db.row_factory = sqlite3.Row

    inv = db.execute("""
        SELECT i.*, 
               s.name sname, s.address saddr, s.gst sgst, s.state sstate,
               r.name rname, r.address raddr, r.gst rgst, r.state rstate
        FROM invoices i
        JOIN sellers s ON i.seller_id = s.id
        JOIN receivers r ON i.receiver_id = r.id
        WHERE i.id=?
    """, (id,)).fetchone()

    items = db.execute("""
        SELECT ii.*,
               p.name pname,
               p.hsn phsn,
               p.gst_rate pgst
        FROM invoice_items ii
        JOIN products p ON ii.product_id = p.id
        WHERE ii.invoice_id=?
    """, (id,)).fetchall()

    db.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial","B",14)
    pdf.cell(0,10,"TAX INVOICE",ln=True,align="C")

    pdf.set_font("Arial","",10)
    pdf.cell(0,8,f"Invoice No: {inv['invoice_no']}",ln=True)
    pdf.cell(0,8,f"Date: {inv['date']}",ln=True)

    # -------- SELLER / RECEIVER --------
    pdf.ln(5)
    pdf.set_font("Arial","B",10)

    start_y = pdf.get_y()
    pdf.cell(95,8,"Seller",1)
    pdf.cell(95,8,"Receiver",1,ln=True)

    pdf.set_font("Arial","",9)

    pdf.set_xy(10, start_y + 8)
    pdf.multi_cell(95,6,safe_text(
        f"{inv['sname']}\n{inv['saddr']}\nGSTIN: {inv['sgst']}"
    ),1)

    pdf.set_xy(105, start_y + 8)
    pdf.multi_cell(95,6,safe_text(
        f"{inv['rname']}\n{inv['raddr']}\nGSTIN: {inv['rgst']}"
    ),1)

    pdf.ln(2)

    # -------- ITEMS TABLE --------
    headers = ["Product","HSN","Rate","Qty","Disc","GST %","Taxable","CGST","SGST","IGST","Total"]
    widths  = [28,12,12,9,10,10,16,13,13,13,14]

    pdf.set_font("Arial","B",9)
    for i in range(len(headers)):
        pdf.cell(widths[i],7,headers[i],1,0,'C')
    pdf.ln()

    pdf.set_font("Arial","",9)
    for it in items:
        total = it["taxable"] + it["cgst"] + it["sgst"] + it["igst"]
        row = [
            it["pname"],
            it["phsn"] or "",
            it["rate"],
            it["qty"],
            it["discount"],
            f"{it['pgst']}%",
            it["taxable"],
            it["cgst"],
            it["sgst"],
            it["igst"],
            total
        ]
        for i in range(len(row)):
            val = f"{row[i]:.2f}" if isinstance(row[i], float) else row[i]
            pdf.cell(widths[i],6,safe_text(val),1,0,'C')
        pdf.ln()

    # -------- TOTALS --------
    pdf.set_font("Arial","B",9)
    pdf.cell(sum(widths[:7]),7,"TOTAL",1,0,'R')
    pdf.cell(widths[7],7,f"{inv['cgst']:.2f}",1,0,'C')
    pdf.cell(widths[8],7,f"{inv['sgst']:.2f}",1,0,'C')
    pdf.cell(widths[9],7,f"{inv['igst']:.2f}",1,0,'C')
    pdf.cell(widths[10],7,f"{inv['total']:.2f}",1,1,'C')
    
    # -------- AMOUNT IN WORDS --------
    pdf.ln(5)
    pdf.set_font("Arial","B",9)
    pdf.cell(40,7,"Amount in Words :",0,0)

    pdf.set_font("Arial","",9)
    pdf.multi_cell(0,7, amount_in_words(inv["total"]))

    # -------- DECLARATION --------
    pdf.ln(4)
    pdf.set_font("Arial","B",9)
    pdf.cell(0,7,"Declaration",ln=True)

    pdf.set_font("Arial","",9)
    pdf.multi_cell(
        0,6,
        safe_text(
            "We declare that this invoice shows the actual price of goods "
            "and all the particulars are true and correct."
        )
    )
    
    # -------- AUTHORISED SIGNATORY --------
    pdf.ln(15)
    pdf.set_font("Arial","B",9)
    pdf.cell(0,7,"For Authorised Signatory",ln=True,align="R")

    pdf.ln(15)
    pdf.cell(0,7,"__________________________",ln=True,align="R")    

    import tempfile
    tmpdir = tempfile.gettempdir()
    path = os.path.join(
        tmpdir,
        f"GST_Invoice_{safe_text(inv['invoice_no']).replace('/','-')}.pdf"
    )
    pdf.output(path)
    return send_file(path, as_attachment=True)

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)









