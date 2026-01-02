from api.schemas.lead import LeadIn

VALID_ZIP_LENGTH = 5

async def validate_lead(payload: LeadIn) -> None:
    if not payload.name.strip():
        raise ValueError('Name is required')
    if not payload.phone.strip():
        raise ValueError('Phone number is required')
    if len(payload.zip.strip()) != VALID_ZIP_LENGTH:
        raise ValueError('ZIP code must be five digits')
    if not payload.consent:
        raise ValueError('Consent is required to process leads')
