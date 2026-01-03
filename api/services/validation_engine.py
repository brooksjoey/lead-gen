from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from .normalization import normalize_contact, NormalizedContact
from .logging import get_logger

logger = get_logger(__name__)

class ValidationRuleType(Enum):
    REQUIRED_FIELD = "required_field"
    FORMAT_VALIDATION = "format_validation"
    ALLOWED_VALUES = "allowed_values"
    CUSTOM_LOGIC = "custom_logic"
    DUPLICATE_DETECTION = "duplicate_detection"

class ValidationResultCode(Enum):
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    FRAUD = "fraud"
    TIMEOUT = "timeout"

@dataclass(frozen=True)
class ValidationRule:
    type: ValidationRuleType
    field: Optional[str] = None
    condition: Optional[Dict] = None
    error_code: str = "validation_failed"
    error_message: Optional[str] = None
    severity: str = "error"  # error, warning, info

@dataclass(frozen=True)
class ValidationResult:
    lead_id: int
    is_valid: bool
    result_code: ValidationResultCode
    validation_time_ms: float
    rules_evaluated: int
    rules_passed: int
    rules_failed: int
    failures: List[Dict] = None
    warnings: List[Dict] = None
    duplicate_of: Optional[int] = None
    fraud_score: Optional[float] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.failures is None:
            self.failures = []
        if self.warnings is None:
            self.warnings = []
        if self.metadata is None:
            self.metadata = {}

class ValidationError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

class ValidationEngine:
    def __init__(self, redis_client: Optional[Redis] = None, 
                 timeout_seconds: int = 30, max_rules_per_lead: int = 50):
        self.redis = redis_client
        self.timeout_seconds = timeout_seconds
        self.max_rules_per_lead = max_rules_per_lead
        self._rule_processors = {
            ValidationRuleType.REQUIRED_FIELD: self._process_required_field,
            ValidationRuleType.FORMAT_VALIDATION: self._process_format_validation,
            ValidationRuleType.ALLOWED_VALUES: self._process_allowed_values,
            ValidationRuleType.DUPLICATE_DETECTION: self._process_duplicate_detection,
            ValidationRuleType.CUSTOM_LOGIC: self._process_custom_logic,
        }
    
    async def validate_lead(self, session: AsyncSession, lead_id: int) -> ValidationResult:
        start_time = datetime.now()
        execution_id = str(uuid4())
        validation_start = datetime.now()
        
        try:
            logger.info("validation.start", 
                       lead_id=lead_id, 
                       execution_id=execution_id)
            
            # Load lead with lock
            lead = await self._get_lead_for_validation(session, lead_id)
            
            if lead.status != "received":
                return ValidationResult(
                    lead_id=lead_id,
                    is_valid=lead.status == "validated",
                    result_code=ValidationResultCode.VALID if lead.status == "validated" else ValidationResultCode.INVALID,
                    validation_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                    rules_evaluated=0,
                    rules_passed=0,
                    rules_failed=0,
                    metadata={"previous_status": lead.status}
                )
            
            # Load validation policy
            policy = await self._load_validation_policy(session, lead.offer_id)
            
            # Check cache for validation result
            cache_key = f"validation:{lead.offer_id}:{hashlib.md5(lead.email.encode()).hexdigest()[:16]}"
            cached_result = await self._get_cached_validation(cache_key)
            
            if cached_result:
                logger.info("validation.cache_hit", 
                           lead_id=lead_id, 
                           cache_key=cache_key)
                # Apply cached validation decision
                await self._apply_cached_validation(session, lead_id, cached_result)
                return ValidationResult(**cached_result, metadata={"cache_hit": True})
            
            # Parse rules from policy
            rules = self._parse_validation_rules(policy.rules)
            
            # Limit rules to prevent DoS
            if len(rules) > self.max_rules_per_lead:
                rules = rules[:self.max_rules_per_lead]
                logger.warning("validation.rules_truncated",
                             lead_id=lead_id,
                             original_count=len(rules),
                             truncated_to=self.max_rules_per_lead)
            
            # Execute validation with timeout
            try:
                validation_task = asyncio.create_task(
                    self._execute_validation_rules(session, lead, rules)
                )
                validation_result = await asyncio.wait_for(
                    validation_task, 
                    timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error("validation.timeout",
                           lead_id=lead_id,
                           timeout_seconds=self.timeout_seconds)
                
                # Mark as timeout but don't fail the lead
                await self._handle_validation_timeout(session, lead_id)
                
                return ValidationResult(
                    lead_id=lead_id,
                    is_valid=True,  # Default to valid on timeout to avoid blocking leads
                    result_code=ValidationResultCode.TIMEOUT,
                    validation_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                    rules_evaluated=len(rules),
                    rules_passed=0,
                    rules_failed=0,
                    warnings=[{
                        "code": "validation_timeout",
                        "message": f"Validation exceeded {self.timeout_seconds} second timeout"
                    }]
                )
            
            # Update lead based on validation result
            await self._update_lead_validation(session, lead_id, validation_result)
            
            # Cache successful validations
            if validation_result.is_valid:
                await self._cache_validation_result(cache_key, validation_result)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.info("validation.complete",
                       lead_id=lead_id,
                       is_valid=validation_result.is_valid,
                       rules_evaluated=validation_result.rules_evaluated,
                       rules_failed=validation_result.rules_failed,
                       execution_ms=execution_time)
            
            return validation_result
            
        except Exception as e:
            logger.error("validation.error",
                        lead_id=lead_id,
                        execution_id=execution_id,
                        error=str(e),
                        traceback=True)
            
            # On validation engine failure, default to valid to avoid blocking leads
            await self._handle_validation_error(session, lead_id)
            
            return ValidationResult(
                lead_id=lead_id,
                is_valid=True,  # Fail open for system errors
                result_code=ValidationResultCode.VALID,
                validation_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                rules_evaluated=0,
                rules_passed=0,
                rules_failed=0,
                warnings=[{
                    "code": "validation_system_error",
                    "message": f"Validation system error: {str(e)[:100]}"
                }]
            )
    
    async def _get_lead_for_validation(self, session: AsyncSession, lead_id: int):
        """Load lead with FOR UPDATE SKIP LOCKED."""
        query = text("""
            SELECT 
                l.id, l.offer_id, l.source_id, l.status,
                l.name, l.email, l.phone, l.country_code,
                l.postal_code, l.city, l.region_code,
                l.normalized_email, l.normalized_phone,
                o.validation_policy_id
            FROM leads l
            JOIN offers o ON o.id = l.offer_id
            WHERE l.id = :lead_id
            FOR UPDATE SKIP LOCKED
        """)
        
        result = await session.execute(query, {"lead_id": lead_id})
        row = result.mappings().first()
        
        if not row:
            raise ValidationError(
                code="lead_not_found",
                message=f"Lead {lead_id} not found or locked"
            )
        
        return row
    
    async def _load_validation_policy(self, session: AsyncSession, offer_id: int) -> Dict:
        query = text("""
            SELECT vp.id, vp.name, vp.version, vp.rules, vp.is_active
            FROM validation_policies vp
            JOIN offers o ON o.validation_policy_id = vp.id
            WHERE o.id = :offer_id AND vp.is_active = TRUE
        """)
        
        result = await session.execute(query, {"offer_id": offer_id})
        row = result.mappings().first()
        
        if not row:
            raise ValidationError(
                code="validation_policy_not_found",
                message=f"No active validation policy for offer {offer_id}"
            )
        
        return {
            "id": row.id,
            "name": row.name,
            "version": row.version,
            "rules": row.rules if isinstance(row.rules, dict) else json.loads(row.rules),
            "is_active": row.is_active
        }
    
    def _parse_validation_rules(self, policy_rules: Dict) -> List[ValidationRule]:
        rules = []
        
        # Required fields
        required_fields = policy_rules.get("required_fields", [])
        for field in required_fields:
            rules.append(ValidationRule(
                type=ValidationRuleType.REQUIRED_FIELD,
                field=field,
                error_code=f"required_field_missing_{field}",
                error_message=f"Field '{field}' is required"
            ))
        
        # Format validations
        format_rules = policy_rules.get("format_validations", {})
        for field, pattern in format_rules.items():
            rules.append(ValidationRule(
                type=ValidationRuleType.FORMAT_VALIDATION,
                field=field,
                condition={"pattern": pattern},
                error_code=f"invalid_format_{field}",
                error_message=f"Field '{field}' has invalid format"
            ))
        
        # Allowed values
        allowed_values = policy_rules.get("allowed_values", {})
        for field, values in allowed_values.items():
            rules.append(ValidationRule(
                type=ValidationRuleType.ALLOWED_VALUES,
                field=field,
                condition={"values": values},
                error_code=f"invalid_value_{field}",
                error_message=f"Field '{field}' has disallowed value"
            ))
        
        # Duplicate detection
        duplicate_config = policy_rules.get("duplicate_detection", {})
        if duplicate_config.get("enabled", False):
            rules.append(ValidationRule(
                type=ValidationRuleType.DUPLICATE_DETECTION,
                condition=duplicate_config,
                error_code="duplicate_lead",
                error_message="Duplicate lead detected"
            ))
        
        # Custom logic (plugins)
        custom_rules = policy_rules.get("custom_rules", [])
        for custom_rule in custom_rules:
            rules.append(ValidationRule(
                type=ValidationRuleType.CUSTOM_LOGIC,
                condition=custom_rule,
                error_code=custom_rule.get("error_code", "custom_validation_failed"),
                error_message=custom_rule.get("error_message"),
                severity=custom_rule.get("severity", "error")
            ))
        
        return rules
    
    async def _execute_validation_rules(self, session: AsyncSession, 
                                       lead: Dict, rules: List[ValidationRule]) -> ValidationResult:
        failures = []
        warnings = []
        rules_evaluated = 0
        rules_passed = 0
        rules_failed = 0
        duplicate_of = None
        fraud_score = None
        
        # Normalize contact info first
        normalized = normalize_contact(lead.email, lead.phone)
        
        for rule in rules:
            rules_evaluated += 1
            processor = self._rule_processors.get(rule.type)
            
            if not processor:
                logger.warning("validation.unknown_rule_type",
                             rule_type=rule.type.value,
                             lead_id=lead.id)
                continue
            
            try:
                rule_result = await processor(session, lead, rule, normalized)
                
                if rule_result.get("passed", False):
                    rules_passed += 1
                    if rule_result.get("warning"):
                        warnings.append({
                            "rule_type": rule.type.value,
                            "field": rule.field,
                            "code": rule.error_code,
                            "message": rule_result.get("warning")
                        })
                else:
                    rules_failed += 1
                    failure_data = {
                        "rule_type": rule.type.value,
                        "field": rule.field,
                        "code": rule.error_code,
                        "message": rule.error_message or rule_result.get("error", "Validation failed")
                    }
                    
                    if rule.severity == "warning":
                        warnings.append(failure_data)
                    else:
                        failures.append(failure_data)
                    
                    # Extract duplicate info if applicable
                    if rule.type == ValidationRuleType.DUPLICATE_DETECTION:
                        duplicate_of = rule_result.get("duplicate_of")
                    
                    # Extract fraud score if applicable
                    if rule.type == ValidationRuleType.CUSTOM_LOGIC:
                        if "fraud_score" in rule_result:
                            fraud_score = rule_result["fraud_score"]
                
                # Break early if critical failure
                if failures and rule.severity == "error":
                    break
                    
            except Exception as e:
                logger.error("validation.rule_execution_error",
                           lead_id=lead.id,
                           rule_type=rule.type.value,
                           error=str(e))
                rules_failed += 1
                failures.append({
                    "rule_type": rule.type.value,
                    "field": rule.field,
                    "code": "rule_execution_error",
                    "message": f"Rule execution failed: {str(e)[:100]}"
                })
        
        is_valid = len([f for f in failures if f.get("severity", "error") == "error"]) == 0
        
        result_code = ValidationResultCode.VALID if is_valid else ValidationResultCode.INVALID
        if duplicate_of:
            result_code = ValidationResultCode.DUPLICATE
        elif fraud_score and fraud_score > 0.8:
            result_code = ValidationResultCode.FRAUD
        
        return ValidationResult(
            lead_id=lead.id,
            is_valid=is_valid,
            result_code=result_code,
            validation_time_ms=(datetime.now() - datetime.fromisoformat(str(lead.get("created_at", datetime.now())))).total_seconds() * 1000,
            rules_evaluated=rules_evaluated,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            failures=failures,
            warnings=warnings,
            duplicate_of=duplicate_of,
            fraud_score=fraud_score,
            metadata={
                "normalized_email": normalized.email,
                "normalized_phone": normalized.phone,
                "phone_format": normalized.phone_format.value
            }
        )
    
    async def _process_required_field(self, session: AsyncSession, 
                                     lead: Dict, rule: ValidationRule, 
                                     normalized: NormalizedContact) -> Dict:
        field_value = lead.get(rule.field)
        
        if field_value is None or (isinstance(field_value, str) and not field_value.strip()):
            return {
                "passed": False,
                "error": f"Field '{rule.field}' is required and empty"
            }
        
        return {"passed": True}
    
    async def _process_format_validation(self, session: AsyncSession,
                                        lead: Dict, rule: ValidationRule,
                                        normalized: NormalizedContact) -> Dict:
        if not rule.field or not rule.condition:
            return {"passed": True}
        
        field_value = lead.get(rule.field)
        if not field_value:
            return {"passed": True}  # Empty fields handled by required rule
        
        pattern = rule.condition.get("pattern")
        if not pattern:
            return {"passed": True}
        
        try:
            regex = re.compile(pattern)
            if not regex.match(str(field_value)):
                return {
                    "passed": False,
                    "error": f"Field '{rule.field}' doesn't match pattern"
                }
        except re.error:
            logger.error("validation.invalid_regex",
                       field=rule.field,
                       pattern=pattern)
            return {"passed": True}  # Don't fail on bad regex
        
        return {"passed": True}
    
    async def _process_allowed_values(self, session: AsyncSession,
                                     lead: Dict, rule: ValidationRule,
                                     normalized: NormalizedContact) -> Dict:
        if not rule.field or not rule.condition:
            return {"passed": True}
        
        field_value = lead.get(rule.field)
        if field_value is None:
            return {"passed": True}  # Empty handled elsewhere
        
        allowed_values = rule.condition.get("values", [])
        if not allowed_values:
            return {"passed": True}
        
        if str(field_value).strip() not in allowed_values:
            return {
                "passed": False,
                "error": f"Field '{rule.field}' value not in allowed list"
            }
        
        return {"passed": True}
    
    async def _process_duplicate_detection(self, session: AsyncSession,
                                          lead: Dict, rule: ValidationRule,
                                          normalized: NormalizedContact) -> Dict:
        config = rule.condition or {}
        
        if not config.get("enabled", False):
            return {"passed": True}
        
        window_hours = config.get("window_hours", 24)
        match_keys = config.get("keys", ["phone", "email"])
        match_mode = config.get("match_mode", "any")
        include_sources = config.get("include_sources", "any")
        action = config.get("action", "reject")
        
        # Build query based on match keys
        conditions = []
        params = {
            "offer_id": lead.offer_id,
            "lead_id": lead.id,
            "window_hours": window_hours
        }
        
        if "email" in match_keys and normalized.email:
            conditions.append("(normalized_email = :email)")
            params["email"] = normalized.email
        
        if "phone" in match_keys and normalized.phone:
            conditions.append("(normalized_phone = :phone)")
            params["phone"] = normalized.phone
        
        if not conditions:
            return {"passed": True}
        
        where_condition = " OR ".join(conditions)
        
        # Add source restriction
        source_condition = ""
        if include_sources == "same_source_only":
            source_condition = "AND source_id = :source_id"
            params["source_id"] = lead.source_id
        
        # Build final query
        query = text(f"""
            SELECT id, created_at
            FROM leads
            WHERE offer_id = :offer_id
            AND id != :lead_id
            AND created_at >= NOW() - INTERVAL ':window_hours HOURS'
            AND status NOT IN ('rejected', 'invalid')
            {source_condition}
            AND ({where_condition})
            ORDER BY created_at DESC
            LIMIT 1
        """)
        
        result = await session.execute(query, params)
        duplicate = result.mappings().first()
        
        if duplicate:
            return {
                "passed": action != "reject",
                "duplicate_of": duplicate.id,
                "error": f"Duplicate of lead {duplicate.id} from {duplicate.created_at}"
            }
        
        return {"passed": True}
    
    async def _process_custom_logic(self, session: AsyncSession,
                                   lead: Dict, rule: ValidationRule,
                                   normalized: NormalizedContact) -> Dict:
        # Custom logic plugins would be loaded and executed here
        # For now, implement some common custom validations
        
        config = rule.condition or {}
        rule_type = config.get("type")
        
        if rule_type == "disposable_email":
            # Check against known disposable email domains
            disposable_domains = config.get("domains", [])
            email_domain = lead.email.split("@")[-1].lower() if lead.email else ""
            
            if email_domain in disposable_domains:
                return {
                    "passed": False,
                    "error": "Disposable email domain not allowed"
                }
        
        elif rule_type == "geographic_restriction":
            # Check postal code/city restrictions
            allowed_areas = config.get("allowed_areas", {})
            
            if lead.postal_code and allowed_areas.get("postal_codes"):
                if lead.postal_code not in allowed_areas["postal_codes"]:
                    return {
                        "passed": False,
                        "error": "Postal code not in service area"
                    }
            
            if lead.city and allowed_areas.get("cities"):
                if lead.city.lower() not in [c.lower() for c in allowed_areas["cities"]]:
                    return {
                        "passed": False,
                        "error": "City not in service area"
                    }
        
        elif rule_type == "fraud_detection":
            # Simple fraud detection based on patterns
            fraud_score = 0.0
            
            # Check for gibberish names
            if lead.name and len(set(lead.name.lower())) < 3:
                fraud_score += 0.3
            
            # Check for recent duplicate IP
            if lead.get("ip_address"):
                ip_query = text("""
                    SELECT COUNT(*) as count
                    FROM leads
                    WHERE offer_id = :offer_id
                    AND ip_address = :ip_address
                    AND created_at >= NOW() - INTERVAL '1 HOUR'
                """)
                ip_result = await session.execute(ip_query, {
                    "offer_id": lead.offer_id,
                    "ip_address": lead.ip_address
                })
                ip_count = ip_result.scalar() or 0
                
                if ip_count > 5:
                    fraud_score += min(0.5, ip_count * 0.1)
            
            if fraud_score > config.get("threshold", 0.7):
                return {
                    "passed": False,
                    "error": "Potential fraud detected",
                    "fraud_score": fraud_score
                }
            
            return {
                "passed": True,
                "fraud_score": fraud_score
            }
        
        return {"passed": True}
    
    async def _update_lead_validation(self, session: AsyncSession, 
                                     lead_id: int, result: ValidationResult):
        if result.is_valid:
            status = "validated"
            validation_reason = None
        elif result.result_code == ValidationResultCode.DUPLICATE:
            status = "rejected"
            validation_reason = "duplicate_lead"
        elif result.result_code == ValidationResultCode.FRAUD:
            status = "rejected"
            validation_reason = "fraud_detected"
        else:
            status = "rejected"
            validation_reason = "validation_failed"
        
        # Update lead with validation result
        query = text("""
            UPDATE leads 
            SET 
                status = :status,
                validation_reason = :reason,
                updated_at = NOW(),
                validation_result = :result_json,
                duplicate_of_lead_id = :duplicate_of,
                fraud_score = :fraud_score
            WHERE id = :lead_id 
            AND status = 'received'
            RETURNING id
        """)
        
        result_data = {
            "is_valid": result.is_valid,
            "result_code": result.result_code.value,
            "rules_evaluated": result.rules_evaluated,
            "rules_failed": result.rules_failed,
            "failures": result.failures,
            "warnings": result.warnings
        }
        
        await session.execute(query, {
            "lead_id": lead_id,
            "status": status,
            "reason": validation_reason,
            "result_json": json.dumps(result_data),
            "duplicate_of": result.duplicate_of,
            "fraud_score": result.fraud_score
        })
    
    async def _handle_validation_timeout(self, session: AsyncSession, lead_id: int):
        """Handle validation timeout - mark as validated with warning."""
        query = text("""
            UPDATE leads 
            SET 
                status = 'validated',
                validation_reason = 'validation_timeout',
                updated_at = NOW()
            WHERE id = :lead_id 
            AND status = 'received'
        """)
        
        await session.execute(query, {"lead_id": lead_id})
    
    async def _handle_validation_error(self, session: AsyncSession, lead_id: int):
        """Handle validation engine error - default to valid."""
        query = text("""
            UPDATE leads 
            SET 
                status = 'validated',
                validation_reason = 'system_error_default_valid',
                updated_at = NOW()
            WHERE id = :lead_id 
            AND status = 'received'
        """)
        
        await session.execute(query, {"lead_id": lead_id})
    
    async def _get_cached_validation(self, cache_key: str) -> Optional[Dict]:
        if not self.redis:
            return None
        
        try:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            logger.warning("validation.cache_read_failed", key=cache_key)
        
        return None
    
    async def _apply_cached_validation(self, session: AsyncSession, 
                                      lead_id: int, cached_result: Dict):
        """Apply cached validation result to lead."""
        if cached_result.get("is_valid"):
            status = "validated"
            reason = "cached_validation"
        else:
            status = "rejected"
            reason = "cached_rejection"
        
        query = text("""
            UPDATE leads 
            SET 
                status = :status,
                validation_reason = :reason,
                updated_at = NOW(),
                validation_result = :result_json
            WHERE id = :lead_id 
            AND status = 'received'
        """)
        
        await session.execute(query, {
            "lead_id": lead_id,
            "status": status,
            "reason": reason,
            "result_json": json.dumps(cached_result)
        })
    
    async def _cache_validation_result(self, cache_key: str, result: ValidationResult):
        if not self.redis:
            return
        
        try:
            # Only cache valid results
            if result.is_valid:
                cache_data = {
                    "is_valid": result.is_valid,
                    "result_code": result.result_code.value,
                    "validation_time_ms": result.validation_time_ms,
                    "rules_evaluated": result.rules_evaluated,
                    "rules_failed": result.rules_failed
                }
                
                # Cache for 1 hour
                await self.redis.setex(
                    cache_key,
                    3600,
                    json.dumps(cache_data)
                )
        except Exception:
            logger.warning("validation.cache_write_failed", key=cache_key)

# Global instance
validation_engine = ValidationEngine()