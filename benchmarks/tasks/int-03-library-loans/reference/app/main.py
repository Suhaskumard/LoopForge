from fastapi import FastAPI, HTTPException
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
