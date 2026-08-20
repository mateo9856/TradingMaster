from typing import TypeVar, Optional, Generic
from pydantic import BaseModel, Field

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    status: str = Field(..., description="Status of the response")
    message: Optional[str] = Field(None, description="Optional message providing additional information")
    data: Optional[T] = Field(None, description="The actual data returned in the response")