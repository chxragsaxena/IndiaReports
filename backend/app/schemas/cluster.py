from pydantic import BaseModel


class ClusterResponse(BaseModel):
    latitude: float
    longitude: float
    count: int

    