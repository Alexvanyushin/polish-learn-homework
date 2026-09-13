from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from contextlib import asynccontextmanager
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Database setup
DATABASE_URL = "sqlite:///./auth.db"
engine = create_engine(DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=20,        # Increase from default 5
    max_overflow=40,     # Increase from default 10
    pool_timeout=60,     # Increase timeout from default 30
    pool_pre_ping=True
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database models
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    picture_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserProgress(Base):
    __tablename__ = "user_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mode_id = Column(String, nullable=False, index=True)
    phraze_id = Column(String, nullable=False)
    status = Column(Integer, nullable=False, default=1)  # 1 = learned, 0 = not learned
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('user_id', 'mode_id', 'phraze_id', name='uq_user_mode_phraze'),
    )

class HardPhrase(Base):
    __tablename__ = "hard_phrases"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mode_id = Column(String, nullable=False, index=True)
    phraze_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('user_id', 'mode_id', 'phraze_id', name='uq_user_mode_phraze_hard'),
    )

# Create tables
Base.metadata.create_all(bind=engine)

# Startup function
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load all data sources on startup"""
    global all_b1_topics_data
    try:
        with open("material/all-b1-topics.json", "r", encoding="utf-8") as file:
            all_b1_topics_data = json.load(file)
        print(f"Loaded all-b1-topics.json with {len(all_b1_topics_data.get('data', []))} topics")
    except FileNotFoundError:
        print("material/all-b1-topics.json not found")
        all_b1_topics_data = {"data": []}
    except Exception as e:
        print(f"Error reading material/all-b1-topics.json: {e}")
        all_b1_topics_data = {"data": []}
    yield

# FastAPI app
app = FastAPI(lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/audio", StaticFiles(directory="audio"), name="audio")

# Hardcoded single-user auth
HARDCODED_USER_ID = int(os.getenv("HARDCODED_USER_ID"))

# Global variable to store the course data
all_b1_topics_data: Dict = {}

class VocabularyItem(BaseModel):
    word: str
    phrase: str

class ProgressRequest(BaseModel):
    mode_id: str
    phraze_id: str

class ProgressResponse(BaseModel):
    learned_count: int
    total_count: int
    learned_phraze_ids: List[str]

class HardPhraseRequest(BaseModel):
    mode_id: str
    phraze_id: str

class HardPhraseResponse(BaseModel):
    ru: str
    en: Optional[str] = None
    pl: str
    id: str
    audio: Optional[str] = None
    mode_id: str

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper functions
def get_current_user(db: Session = Depends(get_db)) -> User:
    """Dependency that resolves the single hardcoded user"""
    user = db.query(User).filter(User.id == HARDCODED_USER_ID).first()
    if user is None:
        user = User(id=HARDCODED_USER_ID, email="user@local", name="User")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@app.get("/")
async def root():
    """Serve the main HTML page"""
    return FileResponse("static/index.html")

# Protected API endpoints
@app.get("/api/modes")
async def get_modes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return available modes with their topics and progress"""
    modes_data = []

    # Helper function to get mode progress
    def get_mode_progress(mode_id: str, data_source: Dict):
        total_phrases = 0
        learned_phrases = 0

        for topic in data_source.get("data", []):
            phrases = topic["phrases"]
            phraze_ids = [p.get("id") for p in phrases if p.get("id")]
            total_phrases += len(phrases)

            # Count learned phrases
            if phraze_ids:
                learned_count = db.query(UserProgress).filter(
                    UserProgress.user_id == current_user.id,
                    UserProgress.mode_id == mode_id,
                    UserProgress.phraze_id.in_(phraze_ids),
                    UserProgress.status == 1
                ).count()
                learned_phrases += learned_count

        return {
            "learned_count": learned_phrases,
            "total_count": total_phrases
        }

    # All B1 Topics
    all_b1_progress = get_mode_progress("all-b1-topics", all_b1_topics_data)
    modes_data.append({
        "id": "all-b1-topics",
        "name": "ChatGPT - important B1 topics (12)",
        "type": "topics",
        "progress": all_b1_progress,
        "topics": [
            {
                "name": topic["topic"],
                "count": len(topic["phrases"])
            }
            for topic in all_b1_topics_data.get("data", [])
        ]
    })

    return {"modes": modes_data}

@app.get("/api/topic-phrases")
async def get_topic_phrases(
    mode_id: str,
    topic_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return phrases for a specific topic in a mode"""
    if mode_id == "all-b1-topics":
        data_source = all_b1_topics_data
    else:
        return []

    # Find the topic
    for topic in data_source.get("data", []):
        if topic["topic"] == topic_name:
            phrases = topic["phrases"]

            # Get all phrase IDs for this topic
            phraze_ids = [p.get("id") for p in phrases if p.get("id")]

            # Count learned phrases
            learned_progress = db.query(UserProgress).filter(
                UserProgress.user_id == current_user.id,
                UserProgress.mode_id == mode_id,
                UserProgress.phraze_id.in_(phraze_ids),
                UserProgress.status == 1
            ).all()

            learned_ids = {p.phraze_id for p in learned_progress}
            learned_count = len(learned_ids)

            return {
                "phrases": phrases,
                "progress": {
                    "learned_count": learned_count,
                    "total_count": len(phrases)
                }
            }

    return []

@app.post("/api/progress")
async def mark_progress(
    request: ProgressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a phrase as learned (status=1)"""
    # Check if progress record already exists
    existing = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.mode_id == request.mode_id,
        UserProgress.phraze_id == request.phraze_id
    ).first()

    if existing:
        # Update existing record
        existing.status = 1
        existing.updated_at = datetime.utcnow()
    else:
        # Create new record
        progress = UserProgress(
            user_id=current_user.id,
            mode_id=request.mode_id,
            phraze_id=request.phraze_id,
            status=1
        )
        db.add(progress)

    db.commit()
    return {"message": "Progress marked successfully"}

@app.get("/api/progress", response_model=ProgressResponse)
async def get_progress(
    mode_id: str,
    topic_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get progress for a specific topic/section"""
    # Get the data source for this mode
    if mode_id == "all-b1-topics":
        data_source = all_b1_topics_data
    else:
        return ProgressResponse(learned_count=0, total_count=0, learned_phraze_ids=[])

    # Find the topic
    for topic in data_source.get("data", []):
        if topic["topic"] == topic_name:
            phrases = topic["phrases"]
            total_count = len(phrases)

            # Get all phrase IDs for this topic
            phraze_ids = [p.get("id") for p in phrases if p.get("id")]

            # Get learned phrases
            learned_progress = db.query(UserProgress).filter(
                UserProgress.user_id == current_user.id,
                UserProgress.mode_id == mode_id,
                UserProgress.phraze_id.in_(phraze_ids),
                UserProgress.status == 1
            ).all()

            learned_phraze_ids = [p.phraze_id for p in learned_progress]
            learned_count = len(learned_phraze_ids)

            return ProgressResponse(
                learned_count=learned_count,
                total_count=total_count,
                learned_phraze_ids=learned_phraze_ids
            )

    return ProgressResponse(learned_count=0, total_count=0, learned_phraze_ids=[])

@app.delete("/api/progress/reset")
async def reset_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset all progress for the current user"""
    # Delete all progress records for this user
    deleted_count = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id
    ).delete()

    db.commit()
    return {"message": "Progress reset successfully", "deleted_count": deleted_count}

@app.delete("/api/progress/reset-mode")
async def reset_mode_progress(
    mode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset progress for a specific mode"""
    # Delete all progress records for this user and mode
    deleted_count = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.mode_id == mode_id
    ).delete()

    db.commit()
    return {"message": "Mode progress reset successfully", "deleted_count": deleted_count}

@app.delete("/api/progress/reset-topic")
async def reset_topic_progress(
    mode_id: str,
    topic_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset progress for a specific topic in a mode"""
    # Get the data source for this mode
    if mode_id == "all-b1-topics":
        data_source = all_b1_topics_data
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mode not found"
        )

    # Find the topic and get phrase IDs
    phraze_ids = []
    for topic in data_source.get("data", []):
        if topic["topic"] == topic_name:
            phraze_ids = [p.get("id") for p in topic["phrases"] if p.get("id")]
            break

    if not phraze_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found"
        )

    # Delete all progress records for this user, mode, and topic phrases
    deleted_count = db.query(UserProgress).filter(
        UserProgress.user_id == current_user.id,
        UserProgress.mode_id == mode_id,
        UserProgress.phraze_id.in_(phraze_ids)
    ).delete()

    db.commit()
    return {"message": "Topic progress reset successfully", "deleted_count": deleted_count}

@app.post("/api/hard-phrases")
async def save_hard_phrase(
    request: HardPhraseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save a phrase as hard (for later review)"""
    # Check if already exists
    existing = db.query(HardPhrase).filter(
        HardPhrase.user_id == current_user.id,
        HardPhrase.mode_id == request.mode_id,
        HardPhrase.phraze_id == request.phraze_id
    ).first()

    if existing:
        return {"message": "Phrase already saved as hard"}

    # Create new hard phrase record
    hard_phrase = HardPhrase(
        user_id=current_user.id,
        mode_id=request.mode_id,
        phraze_id=request.phraze_id
    )
    db.add(hard_phrase)
    db.commit()
    return {"message": "Phrase saved as hard successfully"}

@app.get("/api/hard-phrases", response_model=List[HardPhraseResponse])
async def get_hard_phrases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all hard phrases for current user with full phrase data"""
    # Get all hard phrases for this user
    hard_phrases = db.query(HardPhrase).filter(
        HardPhrase.user_id == current_user.id
    ).all()

    if not hard_phrases:
        return []

    # Group by mode_id to fetch from correct data source
    mode_data_sources = {
        "all-b1-topics": all_b1_topics_data,
    }

    result = []
    for hp in hard_phrases:
        mode_id = hp.mode_id
        phraze_id = hp.phraze_id

        # Get the correct data source
        data_source = mode_data_sources.get(mode_id)
        if not data_source:
            continue

        # Find the phrase in the data source
        for topic in data_source.get("data", []):
            for phrase in topic.get("phrases", []):
                if phrase.get("id") == phraze_id:
                    result.append(HardPhraseResponse(
                        ru=phrase.get("ru", ""),
                        en=phrase.get("en"),
                        pl=phrase.get("pl", ""),
                        id=phrase.get("id", ""),
                        audio=phrase.get("audio"),
                        mode_id=mode_id
                    ))
                    break
            if any(p.get("id") == phraze_id for p in topic.get("phrases", [])):
                break

    return result

@app.delete("/api/hard-phrases/{phraze_id}")
async def remove_hard_phrase(
    phraze_id: str,
    mode_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a phrase from hard list (when marked as OK)"""
    hard_phrase = db.query(HardPhrase).filter(
        HardPhrase.user_id == current_user.id,
        HardPhrase.mode_id == mode_id,
        HardPhrase.phraze_id == phraze_id
    ).first()

    if not hard_phrase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hard phrase not found"
        )

    db.delete(hard_phrase)
    db.commit()
    return {"message": "Hard phrase removed successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
