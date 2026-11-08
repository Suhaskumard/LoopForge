from fastapi import FastAPI, HTTPException, Response

app = FastAPI()
NOTES: dict[int, dict] = {1: {"id": 1, "text": "first"}, 2: {"id": 2, "text": "second"}}


@app.get("/notes")
def list_notes():
    return list(NOTES.values())


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int):
    if note_id not in NOTES:
        raise HTTPException(status_code=404, detail="not found")
    NOTES.pop(note_id)
    return Response(status_code=204)


@app.post("/notes", status_code=201)
def add_note(note: dict):
    note_id = max(NOTES, default=0) + 1
    NOTES[note_id] = {"id": note_id, "text": str(note.get("text", ""))}
    return NOTES[note_id]
