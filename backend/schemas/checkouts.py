from pydantic import BaseModel, Field


class ReturnRequest(BaseModel):
    """
    Powers POST /checkouts/{id}/return. `quantity` is how many units are
    being handed back RIGHT NOW -- it does not have to equal the full
    outstanding amount, which is what enables partial returns (requirement
    #5 from an earlier pass: Quantified Returns).
    """
    quantity: int = Field(..., ge=1)
