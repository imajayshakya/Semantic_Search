from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
import uuid

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/toolsdb")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = "tools"

# Initialize FastAPI
app = FastAPI(
    title="AI Tools Management API",
    description="Backend service for managing AI tools with semantic search",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
Base = declarative_base()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Models
class Tool(Base):
    __tablename__ = "tools"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, index=True)
    name = Column(String, index=True)
    description = Column(Text)
    tags = Column(JSON)
    tool_metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SearchHistory(Base):
    __tablename__ = "search_history"
    
    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text)
    results = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize embedding model
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
EMBEDDING_DIM = 384

# Initialize Qdrant client
qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# Create collection if it doesn't exist
try:
    qdrant_client.get_collection(COLLECTION_NAME)
except:
    qdrant_client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )

# Pydantic models
class ToolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    tags: List[str] = Field(default_factory=list)
    tool_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ToolUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    tool_metadata: Optional[Dict[str, Any]] = None

class ToolResponse(BaseModel):
    id: int
    uuid: str
    name: str
    description: str
    tags: List[str]
    tool_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=50)

class SearchResult(BaseModel):
    tool: ToolResponse
    score: float

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper functions
def create_embedding(text: str) -> List[float]:
    """Generate embedding for text"""
    return embedding_model.encode(text).tolist()

def tool_to_text(name: str, description: str, tags: List[str]) -> str:
    """Convert tool details to searchable text"""
    tags_str = ", ".join(tags) if tags else ""
    return f"{name}. {description}. Tags: {tags_str}"

# API Endpoints
@app.get("/")
def root():
    return {
        "message": "AI Tools Management API",
        "version": "1.0.0",
        "endpoints": {
            "insert": "/tools/",
            "search": "/tools/search",
            "get_all": "/tools/",
            "get_one": "/tools/{tool_uuid}",
            "update": "/tools/{tool_uuid}",
            "delete": "/tools/{tool_uuid}",
            "history": "/search/history"
        }
    }

@app.post("/tools/", response_model=ToolResponse, status_code=201)
def insert_tool(tool: ToolCreate, db: Session = Depends(get_db)):
    """Insert a new tool into both SQL and vector databases"""
    try:
        # Generate UUID
        tool_uuid = str(uuid.uuid4())
        
        # Create SQL entry
        db_tool = Tool(
            uuid=tool_uuid,
            name=tool.name,
            description=tool.description,
            tags=tool.tags,
            tool_metadata=tool.tool_metadata
        )
        db.add(db_tool)
        db.commit()
        db.refresh(db_tool)
        
        # Create embedding and store in Qdrant
        text_for_embedding = tool_to_text(tool.name, tool.description, tool.tags)
        embedding = create_embedding(text_for_embedding)
        
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=tool_uuid,
                    vector=embedding,
                    payload={
                        "name": tool.name,
                        "description": tool.description,
                        "tags": tool.tags,
                        "metadata": tool.tool_metadata,
                        "db_id": db_tool.id
                    }
                )
            ]
        )
        
        return db_tool
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error inserting tool: {str(e)}")

@app.get("/tools/", response_model=List[ToolResponse])
def get_all_tools(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Get all tools from the database"""
    tools = db.query(Tool).offset(skip).limit(limit).all()
    return tools

@app.get("/tools/{tool_uuid}", response_model=ToolResponse)
def get_tool(tool_uuid: str, db: Session = Depends(get_db)):
    """Get a specific tool by UUID"""
    tool = db.query(Tool).filter(Tool.uuid == tool_uuid).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool

@app.put("/tools/{tool_uuid}", response_model=ToolResponse)
def update_tool(tool_uuid: str, tool_update: ToolUpdate, db: Session = Depends(get_db)):
    """Update an existing tool"""
    try:
        db_tool = db.query(Tool).filter(Tool.uuid == tool_uuid).first()
        if not db_tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        
        # Update SQL database
        update_data = tool_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_tool, field, value)
        
        db_tool.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_tool)
        
        # Update Qdrant
        text_for_embedding = tool_to_text(
            db_tool.name,
            db_tool.description,
            db_tool.tags
        )
        embedding = create_embedding(text_for_embedding)
        
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=tool_uuid,
                    vector=embedding,
                    payload={
                        "name": db_tool.name,
                        "description": db_tool.description,
                        "tags": db_tool.tags,
                        "metadata": db_tool.tool_metadata,
                        "db_id": db_tool.id
                    }
                )
            ]
        )
        
        return db_tool
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating tool: {str(e)}")

@app.delete("/tools/{tool_uuid}")
def delete_tool(tool_uuid: str, db: Session = Depends(get_db)):
    """Delete a tool from both databases"""
    try:
        db_tool = db.query(Tool).filter(Tool.uuid == tool_uuid).first()
        if not db_tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        
        # Delete from SQL
        db.delete(db_tool)
        db.commit()
        
        # Delete from Qdrant
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=[tool_uuid]
        )
        
        return {"message": "Tool deleted successfully", "uuid": tool_uuid}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting tool: {str(e)}")

@app.post("/tools/search", response_model=List[SearchResult])
def search_tools(search: SearchQuery, db: Session = Depends(get_db)):
    """Perform semantic search on tools"""
    try:
        # Create embedding for query
        query_embedding = create_embedding(search.query)
        
        # Search in Qdrant
        search_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=search.limit
        )
        
        # Fetch full details from SQL database
        results = []
        tool_data_list = []
        
        for result in search_results:
            tool_uuid = result.id
            db_tool = db.query(Tool).filter(Tool.uuid == tool_uuid).first()
            if db_tool:
                results.append({
                    "tool": db_tool,
                    "score": result.score
                })
                tool_data_list.append({
                    "uuid": db_tool.uuid,
                    "name": db_tool.name,
                    "score": result.score
                })
        
        # Store search history
        history_entry = SearchHistory(
            query=search.query,
            results=tool_data_list,
            timestamp=datetime.utcnow()
        )
        db.add(history_entry)
        db.commit()
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching tools: {str(e)}")

@app.get("/search/history")
def get_search_history(limit: int = 50, db: Session = Depends(get_db)):
    """Get search history"""
    history = db.query(SearchHistory).order_by(SearchHistory.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": h.id,
            "query": h.query,
            "results": h.results,
            "timestamp": h.timestamp
        }
        for h in history
    ]

@app.get("/health")
def health_check():
    """Health check endpoint"""
    try:
        # Check database connection
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        
        # Check Qdrant connection
        qdrant_client.get_collection(COLLECTION_NAME)
        
        return {
            "status": "healthy",
            "database": "connected",
            "vector_db": "connected",
            "timestamp": datetime.utcnow()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow()
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)