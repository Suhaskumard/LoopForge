from fastapi import FastAPI, HTTPException, Response
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
