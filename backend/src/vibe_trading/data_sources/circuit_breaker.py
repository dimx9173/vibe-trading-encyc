"""
Circuit Breaker Pattern

Implements the circuit breaker pattern for data source resilience:
- CLOSED: Normal operation
- OPEN: Circuit tripped, requests fail fast
- HALF_OPEN: Testing if service recovered

Prevents cascading failures when data sources are unavailable.
"""
from enum import Enum
from datetime import datetime, timedelta
from typing import Dict


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit tripped
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker implementation"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 1
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self._states: Dict[str, CircuitState] = {}
        self._failure_counts: Dict[str, int] = {}
        self._last_failure_time: Dict[str, datetime] = {}
        self._half_open_calls: Dict[str, int] = {}
    
    def is_available(self, source_name: str) -> bool:
        """Check if data source is available"""
        state = self._states.get(source_name, CircuitState.CLOSED)
        
        if state == CircuitState.CLOSED:
            return True
        
        if state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            last_failure = self._last_failure_time.get(source_name)
            if last_failure and datetime.now() - last_failure > timedelta(seconds=self.recovery_timeout):
                self._states[source_name] = CircuitState.HALF_OPEN
                self._half_open_calls[source_name] = 0
                return True
            return False
        
        if state == CircuitState.HALF_OPEN:
            # Allow limited test calls
            calls = self._half_open_calls.get(source_name, 0)
            return calls < self.half_open_max_calls
        
        return False
    
    def record_success(self, source_name: str):
        """Record successful request"""
        self._failure_counts[source_name] = 0
        self._states[source_name] = CircuitState.CLOSED
        self._half_open_calls.pop(source_name, None)
    
    def record_failure(self, source_name: str):
        """Record failed request"""
        self._failure_counts[source_name] = self._failure_counts.get(source_name, 0) + 1
        self._last_failure_time[source_name] = datetime.now()
        
        if self._failure_counts[source_name] >= self.failure_threshold:
            self._states[source_name] = CircuitState.OPEN
    
    def get_state(self, source_name: str) -> CircuitState:
        """Get current circuit state"""
        return self._states.get(source_name, CircuitState.CLOSED)
    
    def reset(self, source_name: str):
        """Reset circuit breaker for source"""
        self._states.pop(source_name, None)
        self._failure_counts.pop(source_name, None)
        self._last_failure_time.pop(source_name, None)
        self._half_open_calls.pop(source_name, None)
