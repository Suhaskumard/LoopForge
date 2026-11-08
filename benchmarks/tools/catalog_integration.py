"""Integration tasks: several modules/resources that must work together (state shared across
endpoints, invariants across operations). Each app exposes `reset()` for the test harness."""

from typing import Any

RESET = (
    "Define `reset()` in `app/main.py` that clears ALL in-memory state and restarts every id counter at 1 "
    "(used by the test harness). Entry point is `app.main:app`. No database. Include unit tests (pytest)."
)

FIXTURE = '''import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app


@pytest.fixture()
def c():
    m.reset()
    return TestClient(app)
'''


def _task(id_: str, difficulty: str, req: str, criteria: list[str], ref: dict[str, str], test: str) -> dict[str, Any]:
    return {
        "id": id_,
        "category": "integration",
        "difficulty": difficulty,
        "requirement": req + "\n\n" + RESET,
        "acceptance_criteria": criteria,
        "reference": {"app/__init__.py": "", **ref},
        "hidden_test": FIXTURE + test,
        "seed": None,
    }


def tasks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # 1 inventory + orders --------------------------------------------------------------
    out.append(
        _task(
            "int-01-inventory-orders",
            "medium",
            """Build an inventory and ordering API.
- `POST /products` JSON `{"sku": str (unique, non-empty), "name": str, "price": float > 0, "stock": int >= 0}` -> 201 echoing the product; duplicate sku -> 409; invalid -> 422.
- `GET /products/{sku}` -> 200 or 404.
- `POST /orders` JSON `{"sku": str, "qty": int >= 1}` -> 201 `{"id": int (1,2,...), "sku", "qty", "total": price*qty rounded to 2 decimals, "status": "placed"}` and reduces the product's stock by qty. Unknown sku -> 404; qty above stock -> 409 and the stock must stay unchanged.
- `GET /orders/{id}` -> 200 or 404.
- `POST /orders/{id}/cancel` -> 200 with status "cancelled" and the stock is restored; cancelling an already cancelled order -> 409.""",
            ["Orders reduce stock and cancelling restores it", "Insufficient stock is refused without side effects", "Totals are computed from the product price"],
            {
                "app/main.py": '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
PRODUCTS: dict[str, dict] = {}
ORDERS: dict[int, dict] = {}
_ids = {"order": 1}


def reset() -> None:
    PRODUCTS.clear()
    ORDERS.clear()
    _ids["order"] = 1


class Product(BaseModel):
    sku: str = Field(min_length=1)
    name: str
    price: float = Field(gt=0)
    stock: int = Field(ge=0)


class OrderIn(BaseModel):
    sku: str
    qty: int = Field(ge=1)


@app.post("/products", status_code=201)
def add_product(p: Product):
    if p.sku in PRODUCTS:
        raise HTTPException(409, "duplicate sku")
    PRODUCTS[p.sku] = p.model_dump()
    return PRODUCTS[p.sku]


@app.get("/products/{sku}")
def get_product(sku: str):
    if sku not in PRODUCTS:
        raise HTTPException(404, "no such product")
    return PRODUCTS[sku]


@app.post("/orders", status_code=201)
def place(o: OrderIn):
    product = PRODUCTS.get(o.sku)
    if product is None:
        raise HTTPException(404, "no such product")
    if o.qty > product["stock"]:
        raise HTTPException(409, "insufficient stock")
    product["stock"] -= o.qty
    oid = _ids["order"]
    _ids["order"] += 1
    ORDERS[oid] = {"id": oid, "sku": o.sku, "qty": o.qty, "total": round(product["price"] * o.qty, 2), "status": "placed"}
    return ORDERS[oid]


@app.get("/orders/{oid}")
def get_order(oid: int):
    if oid not in ORDERS:
        raise HTTPException(404, "no such order")
    return ORDERS[oid]


@app.post("/orders/{oid}/cancel")
def cancel(oid: int):
    order = ORDERS.get(oid)
    if order is None:
        raise HTTPException(404, "no such order")
    if order["status"] == "cancelled":
        raise HTTPException(409, "already cancelled")
    PRODUCTS[order["sku"]]["stock"] += order["qty"]
    order["status"] = "cancelled"
    return order
'''
            },
            '''
def product(c, sku="A1", stock=5, price=2.5):
    return c.post("/products", json={"sku": sku, "name": "Thing", "price": price, "stock": stock})


def test_product_validation_and_duplicates(c):
    assert product(c).status_code == 201
    assert product(c).status_code == 409
    assert c.post("/products", json={"sku": "", "name": "x", "price": 1, "stock": 1}).status_code == 422
    assert c.post("/products", json={"sku": "B", "name": "x", "price": 0, "stock": 1}).status_code == 422
    assert c.post("/products", json={"sku": "B", "name": "x", "price": 1, "stock": -1}).status_code == 422
    assert c.get("/products/A1").json()["stock"] == 5 and c.get("/products/none").status_code == 404


def test_order_reduces_stock_and_computes_total(c):
    product(c, stock=5, price=2.5)
    r = c.post("/orders", json={"sku": "A1", "qty": 3})
    assert r.status_code == 201
    assert r.json() == {"id": 1, "sku": "A1", "qty": 3, "total": 7.5, "status": "placed"}
    assert c.get("/products/A1").json()["stock"] == 2
    assert c.get("/orders/1").json()["total"] == 7.5


def test_ordering_exactly_the_remaining_stock_is_allowed(c):
    product(c, stock=2)
    assert c.post("/orders", json={"sku": "A1", "qty": 2}).status_code == 201
    assert c.get("/products/A1").json()["stock"] == 0
    assert c.post("/orders", json={"sku": "A1", "qty": 1}).status_code == 409


def test_insufficient_stock_has_no_side_effects(c):
    product(c, stock=2)
    assert c.post("/orders", json={"sku": "A1", "qty": 3}).status_code == 409
    assert c.get("/products/A1").json()["stock"] == 2
    assert c.get("/orders/1").status_code == 404
    assert c.post("/orders", json={"sku": "A1", "qty": 1}).json()["id"] == 1


def test_unknown_sku_and_bad_qty(c):
    assert c.post("/orders", json={"sku": "nope", "qty": 1}).status_code == 404
    product(c)
    assert c.post("/orders", json={"sku": "A1", "qty": 0}).status_code == 422


def test_cancel_restores_stock_once(c):
    product(c, stock=5)
    c.post("/orders", json={"sku": "A1", "qty": 4})
    r = c.post("/orders/1/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert c.get("/products/A1").json()["stock"] == 5
    assert c.post("/orders/1/cancel").status_code == 409
    assert c.get("/products/A1").json()["stock"] == 5
    assert c.post("/orders/9/cancel").status_code == 404


def test_totals_round_to_two_decimals(c):
    product(c, stock=10, price=0.1)
    assert c.post("/orders", json={"sku": "A1", "qty": 3}).json()["total"] == 0.3
''',
        )
    )

    # 2 bank transfers -------------------------------------------------------------------
    out.append(
        _task(
            "int-02-bank-transfers",
            "hard",
            """Build a small banking API.
- `POST /accounts` JSON `{"owner": str (non-empty), "balance": float >= 0}` -> 201 `{"id": int (1,2,...), "owner", "balance"}`.
- `GET /accounts/{id}` -> 200 or 404.
- `POST /transfers` JSON `{"from_id": int, "to_id": int, "amount": float > 0}` -> 201 `{"id": int (1,2,...), "from_id", "to_id", "amount"}`; moves money atomically. Unknown account -> 404; `from_id == to_id` -> 422; amount <= 0 -> 422; amount greater than the source balance -> 409 and NO balance changes.
- `GET /accounts/{id}/history` -> 200 list of the transfers involving that account (as sender or receiver) in creation order, each with an extra field `direction` that is `"out"` or `"in"` relative to that account.
Total money in the system is conserved by every operation. Balances are rounded to 2 decimals.""",
            ["Transfers are atomic and conserve money", "Overdrafts are refused without side effects", "History reports direction per account"],
            {
                "app/main.py": '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
ACCOUNTS: dict[int, dict] = {}
TRANSFERS: list[dict] = []
_ids = {"account": 1, "transfer": 1}


def reset() -> None:
    ACCOUNTS.clear()
    TRANSFERS.clear()
    _ids.update(account=1, transfer=1)


class AccountIn(BaseModel):
    owner: str = Field(min_length=1)
    balance: float = Field(ge=0)


class TransferIn(BaseModel):
    from_id: int
    to_id: int
    amount: float = Field(gt=0)


@app.post("/accounts", status_code=201)
def open_account(a: AccountIn):
    aid = _ids["account"]
    _ids["account"] += 1
    ACCOUNTS[aid] = {"id": aid, "owner": a.owner, "balance": round(a.balance, 2)}
    return ACCOUNTS[aid]


@app.get("/accounts/{aid}")
def get_account(aid: int):
    if aid not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    return ACCOUNTS[aid]


@app.post("/transfers", status_code=201)
def transfer(t: TransferIn):
    if t.from_id == t.to_id:
        raise HTTPException(422, "cannot transfer to the same account")
    src, dst = ACCOUNTS.get(t.from_id), ACCOUNTS.get(t.to_id)
    if src is None or dst is None:
        raise HTTPException(404, "no such account")
    if t.amount > src["balance"]:
        raise HTTPException(409, "insufficient funds")
    src["balance"] = round(src["balance"] - t.amount, 2)
    dst["balance"] = round(dst["balance"] + t.amount, 2)
    tid = _ids["transfer"]
    _ids["transfer"] += 1
    TRANSFERS.append({"id": tid, "from_id": t.from_id, "to_id": t.to_id, "amount": t.amount})
    return TRANSFERS[-1]


@app.get("/accounts/{aid}/history")
def history(aid: int):
    if aid not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    return [{**t, "direction": "out" if t["from_id"] == aid else "in"} for t in TRANSFERS if aid in (t["from_id"], t["to_id"])]
'''
            },
            '''
def acct(c, owner, balance):
    return c.post("/accounts", json={"owner": owner, "balance": balance}).json()["id"]


def bal(c, i):
    return c.get(f"/accounts/{i}").json()["balance"]


def xfer(c, a, b, amount):
    return c.post("/transfers", json={"from_id": a, "to_id": b, "amount": amount})


def test_open_and_validate_accounts(c):
    assert c.post("/accounts", json={"owner": "A", "balance": 10}).json() == {"id": 1, "owner": "A", "balance": 10}
    assert c.post("/accounts", json={"owner": "", "balance": 1}).status_code == 422
    assert c.post("/accounts", json={"owner": "B", "balance": -1}).status_code == 422
    assert c.get("/accounts/9").status_code == 404


def test_transfer_moves_money_and_conserves_the_total(c):
    a, b = acct(c, "A", 100), acct(c, "B", 50)
    r = xfer(c, a, b, 30.25)
    assert r.status_code == 201 and r.json() == {"id": 1, "from_id": a, "to_id": b, "amount": 30.25}
    assert bal(c, a) == 69.75 and bal(c, b) == 80.25
    assert bal(c, a) + bal(c, b) == 150


def test_overdraft_is_refused_without_side_effects(c):
    a, b = acct(c, "A", 10), acct(c, "B", 0)
    assert xfer(c, a, b, 10.01).status_code == 409
    assert (bal(c, a), bal(c, b)) == (10, 0)
    assert xfer(c, a, b, 10).status_code == 201
    assert (bal(c, a), bal(c, b)) == (0, 10)


def test_invalid_transfers(c):
    a, b = acct(c, "A", 10), acct(c, "B", 10)
    assert xfer(c, a, a, 1).status_code == 422
    assert xfer(c, a, b, 0).status_code == 422
    assert xfer(c, a, b, -5).status_code == 422
    assert xfer(c, a, 99, 1).status_code == 404
    assert xfer(c, 99, b, 1).status_code == 404
    assert (bal(c, a), bal(c, b)) == (10, 10)


def test_history_has_direction_and_order(c):
    a, b, d = acct(c, "A", 100), acct(c, "B", 100), acct(c, "D", 100)
    xfer(c, a, b, 10)
    xfer(c, b, a, 5)
    xfer(c, b, d, 1)
    h = c.get(f"/accounts/{a}/history").json()
    assert [(x["id"], x["direction"]) for x in h] == [(1, "out"), (2, "in")]
    hb = c.get(f"/accounts/{b}/history").json()
    assert [(x["id"], x["direction"]) for x in hb] == [(1, "in"), (2, "out"), (3, "out")]
    assert c.get("/accounts/99/history").status_code == 404
    assert c.get(f"/accounts/{d}/history").json()[0]["amount"] == 1


def test_rounding_keeps_two_decimals(c):
    a, b = acct(c, "A", 0.3), acct(c, "B", 0)
    xfer(c, a, b, 0.1)
    xfer(c, a, b, 0.2)
    assert bal(c, a) == 0 and bal(c, b) == 0.3
''',
        )
    )

    # 3 library loans ---------------------------------------------------------------------
    out.append(
        _task(
            "int-03-library-loans",
            "medium",
            """Build a library lending API.
- `POST /books` JSON `{"title": str (non-empty)}` -> 201 `{"id": int (1,2,...), "title", "available": true}`.
- `POST /members` JSON `{"name": str (non-empty)}` -> 201 `{"id": int (1,2,...), "name"}`.
- `POST /loans` JSON `{"book_id": int, "member_id": int}` -> 201 `{"id": int (1,2,...), "book_id", "member_id", "returned": false}`; the book becomes unavailable. Unknown book or member -> 404; a book that is already on loan -> 409; a member who already has 3 unreturned loans -> 409.
- `POST /loans/{id}/return` -> 200 with `"returned": true` and the book is available again; returning twice -> 409; unknown loan -> 404.
- `GET /books/{id}` -> 200 or 404. `GET /members/{id}/loans` -> 200 list of that member's UNRETURNED loans (404 for unknown member).""",
            ["A book can be lent to one member at a time", "Members are limited to three active loans", "Returning makes the book available again"],
            {
                "app/main.py": '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
BOOKS: dict[int, dict] = {}
MEMBERS: dict[int, dict] = {}
LOANS: dict[int, dict] = {}
_ids = {"book": 1, "member": 1, "loan": 1}
MAX_LOANS = 3


def reset() -> None:
    BOOKS.clear()
    MEMBERS.clear()
    LOANS.clear()
    _ids.update(book=1, member=1, loan=1)


class BookIn(BaseModel):
    title: str = Field(min_length=1)


class MemberIn(BaseModel):
    name: str = Field(min_length=1)


class LoanIn(BaseModel):
    book_id: int
    member_id: int


@app.post("/books", status_code=201)
def add_book(b: BookIn):
    i = _ids["book"]
    _ids["book"] += 1
    BOOKS[i] = {"id": i, "title": b.title, "available": True}
    return BOOKS[i]


@app.get("/books/{bid}")
def get_book(bid: int):
    if bid not in BOOKS:
        raise HTTPException(404, "no such book")
    return BOOKS[bid]


@app.post("/members", status_code=201)
def add_member(m: MemberIn):
    i = _ids["member"]
    _ids["member"] += 1
    MEMBERS[i] = {"id": i, "name": m.name}
    return MEMBERS[i]


@app.post("/loans", status_code=201)
def lend(loan: LoanIn):
    book, member = BOOKS.get(loan.book_id), MEMBERS.get(loan.member_id)
    if book is None or member is None:
        raise HTTPException(404, "unknown book or member")
    if not book["available"]:
        raise HTTPException(409, "book already on loan")
    active = [x for x in LOANS.values() if x["member_id"] == loan.member_id and not x["returned"]]
    if len(active) >= MAX_LOANS:
        raise HTTPException(409, "loan limit reached")
    i = _ids["loan"]
    _ids["loan"] += 1
    book["available"] = False
    LOANS[i] = {"id": i, "book_id": loan.book_id, "member_id": loan.member_id, "returned": False}
    return LOANS[i]


@app.post("/loans/{lid}/return")
def give_back(lid: int):
    loan = LOANS.get(lid)
    if loan is None:
        raise HTTPException(404, "no such loan")
    if loan["returned"]:
        raise HTTPException(409, "already returned")
    loan["returned"] = True
    BOOKS[loan["book_id"]]["available"] = True
    return loan


@app.get("/members/{mid}/loans")
def member_loans(mid: int):
    if mid not in MEMBERS:
        raise HTTPException(404, "no such member")
    return [x for x in LOANS.values() if x["member_id"] == mid and not x["returned"]]
'''
            },
            '''
def book(c, t="B"):
    return c.post("/books", json={"title": t}).json()["id"]


def member(c, n="M"):
    return c.post("/members", json={"name": n}).json()["id"]


def lend(c, b, m):
    return c.post("/loans", json={"book_id": b, "member_id": m})


def test_creation_and_validation(c):
    assert c.post("/books", json={"title": "Dune"}).json() == {"id": 1, "title": "Dune", "available": True}
    assert c.post("/books", json={"title": ""}).status_code == 422
    assert c.post("/members", json={"name": ""}).status_code == 422
    assert c.get("/books/5").status_code == 404


def test_lending_marks_the_book_unavailable(c):
    b, m = book(c), member(c)
    r = lend(c, b, m)
    assert r.status_code == 201 and r.json() == {"id": 1, "book_id": b, "member_id": m, "returned": False}
    assert c.get(f"/books/{b}").json()["available"] is False


def test_a_book_cannot_be_lent_twice(c):
    b, m1, m2 = book(c), member(c), member(c)
    lend(c, b, m1)
    assert lend(c, b, m2).status_code == 409


def test_unknown_book_or_member(c):
    b, m = book(c), member(c)
    assert lend(c, 99, m).status_code == 404
    assert lend(c, b, 99).status_code == 404
    assert c.get(f"/books/{b}").json()["available"] is True


def test_three_loan_limit_and_return_frees_a_slot(c):
    m = member(c)
    books = [book(c, f"B{i}") for i in range(4)]
    loans = [lend(c, b, m).json()["id"] for b in books[:3]]
    assert lend(c, books[3], m).status_code == 409
    assert c.get(f"/books/{books[3]}").json()["available"] is True
    assert c.post(f"/loans/{loans[0]}/return").status_code == 200
    assert lend(c, books[3], m).status_code == 201


def test_return_rules(c):
    b, m = book(c), member(c)
    lid = lend(c, b, m).json()["id"]
    r = c.post(f"/loans/{lid}/return")
    assert r.json()["returned"] is True and c.get(f"/books/{b}").json()["available"] is True
    assert c.post(f"/loans/{lid}/return").status_code == 409
    assert c.post("/loans/99/return").status_code == 404


def test_member_loans_list_only_unreturned(c):
    m = member(c)
    b1, b2 = book(c), book(c)
    l1 = lend(c, b1, m).json()["id"]
    lend(c, b2, m)
    c.post(f"/loans/{l1}/return")
    assert [x["book_id"] for x in c.get(f"/members/{m}/loans").json()] == [b2]
    assert c.get("/members/99/loans").status_code == 404


def test_returned_book_can_go_to_someone_else(c):
    b, m1, m2 = book(c), member(c), member(c)
    lid = lend(c, b, m1).json()["id"]
    c.post(f"/loans/{lid}/return")
    assert lend(c, b, m2).status_code == 201
''',
        )
    )

    # 4 blog posts + comments ---------------------------------------------------------------
    out.append(
        _task(
            "int-04-blog-comments",
            "medium",
            """Build a blog API with posts and comments.
- `POST /posts` JSON `{"title": str (non-empty), "body": str}` -> 201 `{"id": int (1,2,...), "title", "body", "comment_count": 0}`.
- `GET /posts` -> 200 list of posts in creation order, each with its current `comment_count`. `GET /posts/{id}` -> 200 or 404.
- `POST /posts/{id}/comments` JSON `{"author": str (non-empty), "text": str (1-500 chars)}` -> 201 `{"id": int, "post_id", "author", "text"}`; comment ids are global (1,2,3,... across posts); unknown post -> 404; invalid -> 422.
- `GET /posts/{id}/comments` -> 200 list in creation order (404 for unknown post).
- `DELETE /comments/{id}` -> 204 (404 if unknown) and the post's `comment_count` drops.
- `DELETE /posts/{id}` -> 204 (404 if unknown); its comments are deleted too, so `DELETE /comments/{id}` for them is then 404.""",
            ["Comments belong to posts and are counted", "Deleting a post cascades to its comments", "Comment ids are global"],
            {
                "app/main.py": '''from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
POSTS: dict[int, dict] = {}
COMMENTS: dict[int, dict] = {}
_ids = {"post": 1, "comment": 1}


def reset() -> None:
    POSTS.clear()
    COMMENTS.clear()
    _ids.update(post=1, comment=1)


class PostIn(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""


class CommentIn(BaseModel):
    author: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=500)


def view(p: dict) -> dict:
    return {**p, "comment_count": sum(1 for c in COMMENTS.values() if c["post_id"] == p["id"])}


@app.post("/posts", status_code=201)
def create_post(p: PostIn):
    i = _ids["post"]
    _ids["post"] += 1
    POSTS[i] = {"id": i, "title": p.title, "body": p.body}
    return view(POSTS[i])


@app.get("/posts")
def list_posts():
    return [view(p) for p in POSTS.values()]


@app.get("/posts/{pid}")
def get_post(pid: int):
    if pid not in POSTS:
        raise HTTPException(404, "no such post")
    return view(POSTS[pid])


@app.post("/posts/{pid}/comments", status_code=201)
def add_comment(pid: int, c: CommentIn):
    if pid not in POSTS:
        raise HTTPException(404, "no such post")
    i = _ids["comment"]
    _ids["comment"] += 1
    COMMENTS[i] = {"id": i, "post_id": pid, "author": c.author, "text": c.text}
    return COMMENTS[i]


@app.get("/posts/{pid}/comments")
def list_comments(pid: int):
    if pid not in POSTS:
        raise HTTPException(404, "no such post")
    return [c for c in COMMENTS.values() if c["post_id"] == pid]


@app.delete("/comments/{cid}", status_code=204)
def delete_comment(cid: int):
    if cid not in COMMENTS:
        raise HTTPException(404, "no such comment")
    del COMMENTS[cid]
    return Response(status_code=204)


@app.delete("/posts/{pid}", status_code=204)
def delete_post(pid: int):
    if pid not in POSTS:
        raise HTTPException(404, "no such post")
    del POSTS[pid]
    for cid in [i for i, c in COMMENTS.items() if c["post_id"] == pid]:
        del COMMENTS[cid]
    return Response(status_code=204)
'''
            },
            '''
def post(c, t="T"):
    return c.post("/posts", json={"title": t, "body": "b"}).json()["id"]


def comment(c, pid, text="hi", author="a"):
    return c.post(f"/posts/{pid}/comments", json={"author": author, "text": text})


def test_post_crud_basics(c):
    assert c.post("/posts", json={"title": "Hello", "body": "World"}).json() == {"id": 1, "title": "Hello", "body": "World", "comment_count": 0}
    assert c.post("/posts", json={"title": ""}).status_code == 422
    assert c.get("/posts/7").status_code == 404
    assert [p["id"] for p in c.get("/posts").json()] == [1]


def test_comments_are_global_ids_and_counted(c):
    p1, p2 = post(c), post(c)
    assert comment(c, p1).json() == {"id": 1, "post_id": p1, "author": "a", "text": "hi"}
    assert comment(c, p2).json()["id"] == 2
    assert comment(c, p1).json()["id"] == 3
    assert c.get(f"/posts/{p1}").json()["comment_count"] == 2
    assert [x["comment_count"] for x in c.get("/posts").json()] == [2, 1]
    assert [x["id"] for x in c.get(f"/posts/{p1}/comments").json()] == [1, 3]


def test_comment_validation(c):
    p = post(c)
    assert comment(c, p, text="").status_code == 422
    assert comment(c, p, text="x" * 501).status_code == 422
    assert comment(c, p, text="x" * 500).status_code == 201
    assert comment(c, p, author="").status_code == 422
    assert comment(c, 99).status_code == 404
    assert c.get("/posts/99/comments").status_code == 404


def test_deleting_a_comment_updates_the_count(c):
    p = post(c)
    cid = comment(c, p).json()["id"]
    assert c.delete(f"/comments/{cid}").status_code == 204
    assert c.get(f"/posts/{p}").json()["comment_count"] == 0
    assert c.delete(f"/comments/{cid}").status_code == 404


def test_deleting_a_post_cascades(c):
    p1, p2 = post(c), post(c)
    c1 = comment(c, p1).json()["id"]
    c2 = comment(c, p2).json()["id"]
    assert c.delete(f"/posts/{p1}").status_code == 204
    assert c.get(f"/posts/{p1}").status_code == 404
    assert c.delete(f"/comments/{c1}").status_code == 404
    assert c.get(f"/posts/{p2}/comments").json()[0]["id"] == c2
    assert c.delete("/posts/99").status_code == 404
''',
        )
    )

    # 5 shopping cart with coupons ----------------------------------------------------------
    out.append(
        _task(
            "int-05-cart-coupons",
            "hard",
            """Build a shopping cart API with coupons. The catalogue is fixed in code: `apple` costs 0.50, `bread` 2.20, `cheese` 7.80, `wine` 12.00.
- `POST /carts` -> 201 `{"id": int (1,2,...), "items": [], "subtotal": 0, "discount": 0, "total": 0, "coupon": null}`.
- `POST /carts/{id}/items` JSON `{"product": str, "qty": int >= 1}` -> 200 with the full cart. Unknown product -> 422; unknown cart -> 404. Adding a product already in the cart increases its quantity (items stay one line per product, in first-added order, each `{"product", "qty", "unit_price", "line_total"}`).
- `POST /carts/{id}/coupon` JSON `{"code": str}` -> 200 with the cart, or 404 for an unknown cart, 422 for an unknown code. Codes: `SAVE10` = 10% off the subtotal; `FLAT5` = 5.00 off but only if the subtotal is at least 20.00 (otherwise 409 and no coupon is set). Only one coupon per cart: a second coupon -> 409.
- `GET /carts/{id}` -> 200 with the cart. `subtotal` = sum of line totals; `discount` is recomputed from the coupon whenever the cart is read or changed (so adding items after applying FLAT5 keeps the discount; FLAT5 never makes the total negative); `total = subtotal - discount`. All money values are rounded half-up to 2 decimals.""",
            ["Subtotals, discounts and totals are computed correctly", "Coupon rules are enforced (one per cart, FLAT5 minimum)", "Items merge per product"],
            {
                "app/main.py": '''from decimal import ROUND_HALF_UP, Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
CATALOGUE = {"apple": Decimal("0.50"), "bread": Decimal("2.20"), "cheese": Decimal("7.80"), "wine": Decimal("12.00")}
CARTS: dict[int, dict] = {}
_ids = {"cart": 1}
CENT = Decimal("0.01")


def reset() -> None:
    CARTS.clear()
    _ids["cart"] = 1


class ItemIn(BaseModel):
    product: str
    qty: int = Field(ge=1)


class CouponIn(BaseModel):
    code: str


def money(x: Decimal) -> float:
    return float(x.quantize(CENT, rounding=ROUND_HALF_UP))


def view(cart: dict) -> dict:
    lines = [
        {"product": p, "qty": q, "unit_price": float(CATALOGUE[p]), "line_total": money(CATALOGUE[p] * q)}
        for p, q in cart["lines"].items()
    ]
    subtotal = sum((CATALOGUE[p] * q for p, q in cart["lines"].items()), Decimal(0))
    code = cart["coupon"]
    discount = Decimal(0)
    if code == "SAVE10":
        discount = subtotal * Decimal("0.10")
    elif code == "FLAT5":
        discount = min(Decimal(5), subtotal)
    discount = discount.quantize(CENT, rounding=ROUND_HALF_UP)
    total = max(subtotal.quantize(CENT, rounding=ROUND_HALF_UP) - discount, Decimal(0))
    return {"id": cart["id"], "items": lines, "subtotal": money(subtotal), "discount": float(discount), "total": float(total), "coupon": code}


def get_cart(cid: int) -> dict:
    if cid not in CARTS:
        raise HTTPException(404, "no such cart")
    return CARTS[cid]


@app.post("/carts", status_code=201)
def new_cart():
    i = _ids["cart"]
    _ids["cart"] += 1
    CARTS[i] = {"id": i, "lines": {}, "coupon": None}
    return view(CARTS[i])


@app.post("/carts/{cid}/items")
def add_item(cid: int, item: ItemIn):
    cart = get_cart(cid)
    if item.product not in CATALOGUE:
        raise HTTPException(422, "unknown product")
    cart["lines"][item.product] = cart["lines"].get(item.product, 0) + item.qty
    return view(cart)


@app.post("/carts/{cid}/coupon")
def apply_coupon(cid: int, c: CouponIn):
    cart = get_cart(cid)
    if c.code not in ("SAVE10", "FLAT5"):
        raise HTTPException(422, "unknown coupon")
    if cart["coupon"] is not None:
        raise HTTPException(409, "coupon already applied")
    if c.code == "FLAT5":
        subtotal = sum((CATALOGUE[p] * q for p, q in cart["lines"].items()), Decimal(0))
        if subtotal < 20:
            raise HTTPException(409, "FLAT5 needs a subtotal of at least 20.00")
    cart["coupon"] = c.code
    return view(cart)


@app.get("/carts/{cid}")
def read_cart(cid: int):
    return view(get_cart(cid))
'''
            },
            '''
def cart(c):
    return c.post("/carts").json()["id"]


def add(c, cid, product, qty=1):
    return c.post(f"/carts/{cid}/items", json={"product": product, "qty": qty})


def coupon(c, cid, code):
    return c.post(f"/carts/{cid}/coupon", json={"code": code})


def test_new_cart_is_empty(c):
    assert c.post("/carts").json() == {"id": 1, "items": [], "subtotal": 0, "discount": 0, "total": 0, "coupon": None}
    assert c.get("/carts/9").status_code == 404


def test_items_merge_per_product_and_totals(c):
    cid = cart(c)
    add(c, cid, "apple", 3)
    add(c, cid, "bread", 1)
    r = add(c, cid, "apple", 2).json()
    assert [(i["product"], i["qty"], i["line_total"]) for i in r["items"]] == [("apple", 5, 2.5), ("bread", 1, 2.2)]
    assert r["subtotal"] == 4.7 and r["total"] == 4.7 and r["discount"] == 0


def test_invalid_item_requests(c):
    cid = cart(c)
    assert add(c, cid, "durian").status_code == 422
    assert add(c, cid, "apple", 0).status_code == 422
    assert add(c, 99, "apple").status_code == 404


def test_save10_is_ten_percent_and_rounds_half_up(c):
    cid = cart(c)
    add(c, cid, "bread", 1)
    add(c, cid, "apple", 1)  # 2.70 -> discount 0.27
    r = coupon(c, cid, "SAVE10").json()
    assert (r["subtotal"], r["discount"], r["total"], r["coupon"]) == (2.7, 0.27, 2.43, "SAVE10")
    cid2 = cart(c)
    add(c, cid2, "bread", 1)
    add(c, cid2, "apple", 1)
    add(c, cid2, "apple", 1)  # 3.20 -> 0.32
    assert coupon(c, cid2, "SAVE10").json()["discount"] == 0.32
    cid3 = cart(c)
    add(c, cid3, "apple", 1)
    add(c, cid3, "bread", 1)
    add(c, cid3, "apple", 3)  # 4.20 -> 0.42
    assert coupon(c, cid3, "SAVE10").json()["discount"] == 0.42


def test_discount_follows_later_changes(c):
    cid = cart(c)
    add(c, cid, "wine", 1)
    coupon(c, cid, "SAVE10")
    r = add(c, cid, "wine", 1).json()
    assert (r["subtotal"], r["discount"], r["total"]) == (24.0, 2.4, 21.6)
    assert c.get(f"/carts/{cid}").json()["total"] == 21.6


def test_flat5_requires_twenty_and_is_capped(c):
    cid = cart(c)
    add(c, cid, "wine", 1)
    assert coupon(c, cid, "FLAT5").status_code == 409
    assert c.get(f"/carts/{cid}").json()["coupon"] is None
    add(c, cid, "cheese", 1)  # 19.80 still below 20
    assert coupon(c, cid, "FLAT5").status_code == 409
    add(c, cid, "apple", 1)  # 20.30
    r = coupon(c, cid, "FLAT5").json()
    assert (r["subtotal"], r["discount"], r["total"]) == (20.3, 5.0, 15.3)


def test_flat5_at_exactly_twenty(c):
    cid = cart(c)
    add(c, cid, "cheese", 2)  # 15.60
    add(c, cid, "bread", 2)  # + 4.40 = 20.00
    r = coupon(c, cid, "FLAT5").json()
    assert (r["subtotal"], r["total"]) == (20.0, 15.0)


def test_one_coupon_only_and_unknown_codes(c):
    cid = cart(c)
    add(c, cid, "wine", 2)
    assert coupon(c, cid, "NOPE").status_code == 422
    assert coupon(c, cid, "SAVE10").status_code == 200
    assert coupon(c, cid, "FLAT5").status_code == 409
    assert coupon(c, cid, "SAVE10").status_code == 409
    assert coupon(c, 99, "SAVE10").status_code == 404
    assert c.get(f"/carts/{cid}").json()["coupon"] == "SAVE10"
''',
        )
    )

    # 6 room booking with overlap detection -------------------------------------------------
    out.append(
        _task(
            "int-06-room-booking",
            "hard",
            """Build a meeting-room booking API.
- `POST /rooms` JSON `{"name": str (non-empty, unique), "capacity": int >= 1}` -> 201 `{"id": int (1,2,...), "name", "capacity"}`; duplicate name -> 409.
- `POST /bookings` JSON `{"room_id": int, "start": "YYYY-MM-DDTHH:MM", "end": "YYYY-MM-DDTHH:MM", "attendees": int >= 1}` -> 201 `{"id": int (1,2,...), "room_id", "start", "end", "attendees", "status": "confirmed"}` (start/end echoed as given). Rules: unknown room -> 404; start/end not valid datetimes in that exact format, or `end <= start` -> 422; attendees above the room capacity -> 422; a CONFIRMED booking of the same room that overlaps in time -> 409. Intervals are half-open: a booking that ends exactly when another starts does NOT overlap.
- `DELETE /bookings/{id}` -> 200 with `"status": "cancelled"`; cancelled bookings no longer block the time slot; cancelling twice or an unknown id -> 404.
- `GET /rooms/{id}/bookings` -> 200 the room's CONFIRMED bookings sorted by `start` (404 for unknown room).""",
            ["Overlapping bookings are rejected, adjacent ones allowed", "Cancelled bookings free the slot", "Capacity and datetime validation"],
            {
                "app/main.py": '''from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
ROOMS: dict[int, dict] = {}
BOOKINGS: dict[int, dict] = {}
_ids = {"room": 1, "booking": 1}
FMT = "%Y-%m-%dT%H:%M"


def reset() -> None:
    ROOMS.clear()
    BOOKINGS.clear()
    _ids.update(room=1, booking=1)


class RoomIn(BaseModel):
    name: str = Field(min_length=1)
    capacity: int = Field(ge=1)


class BookingIn(BaseModel):
    room_id: int
    start: str
    end: str
    attendees: int = Field(ge=1)


def parse(value: str) -> datetime:
    try:
        return datetime.strptime(value, FMT)
    except ValueError:
        raise HTTPException(422, "bad datetime") from None


@app.post("/rooms", status_code=201)
def add_room(r: RoomIn):
    if any(x["name"] == r.name for x in ROOMS.values()):
        raise HTTPException(409, "duplicate room name")
    i = _ids["room"]
    _ids["room"] += 1
    ROOMS[i] = {"id": i, "name": r.name, "capacity": r.capacity}
    return ROOMS[i]


@app.post("/bookings", status_code=201)
def book(b: BookingIn):
    room = ROOMS.get(b.room_id)
    if room is None:
        raise HTTPException(404, "no such room")
    start, end = parse(b.start), parse(b.end)
    if end <= start:
        raise HTTPException(422, "end must be after start")
    if b.attendees > room["capacity"]:
        raise HTTPException(422, "over capacity")
    for other in BOOKINGS.values():
        if other["room_id"] == b.room_id and other["status"] == "confirmed":
            if start < parse(other["end"]) and parse(other["start"]) < end:
                raise HTTPException(409, "time slot taken")
    i = _ids["booking"]
    _ids["booking"] += 1
    BOOKINGS[i] = {"id": i, "room_id": b.room_id, "start": b.start, "end": b.end, "attendees": b.attendees, "status": "confirmed"}
    return BOOKINGS[i]


@app.delete("/bookings/{bid}")
def cancel(bid: int):
    booking = BOOKINGS.get(bid)
    if booking is None or booking["status"] == "cancelled":
        raise HTTPException(404, "no such active booking")
    booking["status"] = "cancelled"
    return booking


@app.get("/rooms/{rid}/bookings")
def room_bookings(rid: int):
    if rid not in ROOMS:
        raise HTTPException(404, "no such room")
    rows = [b for b in BOOKINGS.values() if b["room_id"] == rid and b["status"] == "confirmed"]
    return sorted(rows, key=lambda b: parse(b["start"]))
'''
            },
            '''
def room(c, name="Big", cap=10):
    return c.post("/rooms", json={"name": name, "capacity": cap}).json()["id"]


def book(c, rid, start, end, n=2):
    return c.post("/bookings", json={"room_id": rid, "start": start, "end": end, "attendees": n})


D = "2030-01-01T"


def test_rooms(c):
    assert c.post("/rooms", json={"name": "A", "capacity": 4}).json() == {"id": 1, "name": "A", "capacity": 4}
    assert c.post("/rooms", json={"name": "A", "capacity": 4}).status_code == 409
    assert c.post("/rooms", json={"name": "", "capacity": 4}).status_code == 422
    assert c.post("/rooms", json={"name": "B", "capacity": 0}).status_code == 422


def test_booking_is_confirmed_and_echoed(c):
    rid = room(c)
    r = book(c, rid, D + "09:00", D + "10:00", 3)
    assert r.status_code == 201
    assert r.json() == {"id": 1, "room_id": rid, "start": D + "09:00", "end": D + "10:00", "attendees": 3, "status": "confirmed"}


def test_validation(c):
    rid = room(c, cap=5)
    assert book(c, 99, D + "09:00", D + "10:00").status_code == 404
    assert book(c, rid, D + "10:00", D + "09:00").status_code == 422
    assert book(c, rid, D + "10:00", D + "10:00").status_code == 422
    assert book(c, rid, "2030-01-01 09:00", D + "10:00").status_code == 422
    assert book(c, rid, "2030-02-30T09:00", "2030-02-30T10:00").status_code == 422
    assert book(c, rid, D + "09:00", D + "10:00", 6).status_code == 422
    assert book(c, rid, D + "09:00", D + "10:00", 5).status_code == 201


def test_overlaps_conflict_but_adjacent_slots_do_not(c):
    rid = room(c)
    assert book(c, rid, D + "09:00", D + "10:00").status_code == 201
    assert book(c, rid, D + "09:30", D + "10:30").status_code == 409
    assert book(c, rid, D + "08:00", D + "09:30").status_code == 409
    assert book(c, rid, D + "08:00", D + "11:00").status_code == 409  # fully contains
    assert book(c, rid, D + "09:15", D + "09:45").status_code == 409  # fully inside
    assert book(c, rid, D + "10:00", D + "11:00").status_code == 201  # starts when the first ends
    assert book(c, rid, D + "08:00", D + "09:00").status_code == 201  # ends when the first starts


def test_other_rooms_are_independent(c):
    a, b = room(c, "A"), room(c, "B")
    book(c, a, D + "09:00", D + "10:00")
    assert book(c, b, D + "09:00", D + "10:00").status_code == 201


def test_cancel_frees_the_slot(c):
    rid = room(c)
    first = book(c, rid, D + "09:00", D + "10:00").json()["id"]
    r = c.delete(f"/bookings/{first}")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert book(c, rid, D + "09:00", D + "10:00").status_code == 201
    assert c.delete(f"/bookings/{first}").status_code == 404
    assert c.delete("/bookings/99").status_code == 404


def test_room_listing_is_sorted_confirmed_only(c):
    rid = room(c)
    late = book(c, rid, D + "15:00", D + "16:00").json()["id"]
    book(c, rid, D + "09:00", D + "10:00")
    cancelled = book(c, rid, D + "11:00", D + "12:00").json()["id"]
    c.delete(f"/bookings/{cancelled}")
    rows = c.get(f"/rooms/{rid}/bookings").json()
    assert [r["start"] for r in rows] == [D + "09:00", D + "15:00"]
    assert late in [r["id"] for r in rows] and cancelled not in [r["id"] for r in rows]
    assert c.get("/rooms/99/bookings").status_code == 404
''',
        )
    )
    return out
