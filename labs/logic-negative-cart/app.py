from __future__ import annotations

from flask import redirect, request, session

from labkit import Lab

lab = Lab("CARTWHEEL", accent="#e76f51")
app = lab.app

CATALOG = {
    "kite": {"name": "Aero Kite", "price": 120},
    "harness": {"name": "Bar Harness", "price": 80},
    "vault": {"name": "Vault Access Pack", "price": 500},
}


def init():
    session.setdefault("balance", 100)
    session.setdefault("cart", [])


def layout(title: str, body: str) -> object:
    init()
    return lab.page(title, f'<div class="hero"><div class="kicker">CARTWHEEL // FIELD SUPPLY</div><h1>{title}</h1></div>{body}', nav='<a href="/">Shop</a><a href="/cart">Cart</a>')


@app.get("/")
def index():
    init()
    cards = "".join(
        f'''<div class="panel"><h2>{item["name"]}</h2><p>${item["price"]}.00</p>
        <form method="post" action="/add"><input type="hidden" name="item" value="{key}">
        <label>Quantity</label><input name="qty" value="1" type="number">
        <p><button type="submit">Add to cart</button></p></form></div>'''
        for key, item in CATALOG.items()
    )
    return layout(
        "Field supply",
        f'<div class="panel"><h2>Wallet: ${session["balance"]}.00</h2><p>Items are added to a server-side cart. Checkout settles the total against your wallet.</p></div><div class="grid">{cards}</div>',
    )


@app.post("/add")
def add():
    init()
    item = request.form.get("item", "")
    try:
        qty = int(request.form.get("qty", "1"))
    except ValueError:
        qty = 1
    if item not in CATALOG:
        return layout("Unknown item", '<div class="flash err">Unknown catalog item.</div>')
    # VULNERABLE: quantity is trusted as a signed integer with no lower bound.
    session["cart"] = session.get("cart", []) + [{"item": item, "qty": qty}]
    session.modified = True
    return redirect("/cart")


@app.get("/cart")
def cart():
    init()
    lines = []
    total = 0
    for line in session["cart"]:
        item = CATALOG.get(line["item"])
        if not item:
            continue
        subtotal = item["price"] * line["qty"]
        total += subtotal
        lines.append(f'<li>{line["qty"]} × {item["name"]} — ${subtotal}.00</li>')
    return layout(
        "Cart",
        f'<div class="panel"><h2>Cart</h2><ul class="list">{"".join(lines) or "<li>Cart is empty.</li>"}</ul>'
        f'<p>Total: <strong>${total}.00</strong> · Wallet: <strong>${session["balance"]}.00</strong></p>'
        '<form method="post" action="/checkout"><button type="submit">Settle order</button></form>'
        '<p class="note">The quantity field accepts signed integers. Checkout does not reject negative subtotals.</p></div>',
    )


@app.post("/checkout")
def checkout():
    init()
    cart = session.get("cart", [])
    if not cart:
        return layout("Empty cart", '<div class="flash err">Nothing to settle.</div>')
    total = 0
    bought_vault = False
    for line in cart:
        item = CATALOG.get(line["item"])
        if not item:
            continue
        total += item["price"] * line["qty"]
        if line["item"] == "vault" and line["qty"] > 0:
            bought_vault = True
    session["balance"] = session.get("balance", 0) - total
    session["cart"] = []
    session.modified = True
    flag = f'<div class="panel"><h2>Vault access provisioned</h2><pre>{lab.flag("flag")}</pre></div>' if bought_vault else ""
    return layout(
        "Order settled",
        f'<div class="flash ok">Order total ${total}.00. New wallet balance: ${session["balance"]}.00.</div>{flag}',
    )


@app.post("/reset")
def reset():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    lab.run()
