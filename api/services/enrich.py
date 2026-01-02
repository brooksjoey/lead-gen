from api.schemas.lead import LeadIn

async def enrich_lead(payload: LeadIn) -> LeadIn:
    return payload
