"""Network access policy and approval system."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse


class NetworkPolicy:
    """Manages network access approval and domain whitelisting."""
    
    def __init__(self, network_access: bool = False, approved_domains: list[str] | None = None):
        """Initialize network policy.
        
        Args:
            network_access: Global network access flag
            approved_domains: List of pre-approved domains (e.g., ["github.com", "*.openai.com"])
        """
        self._network_access = network_access
        self._approved_domains = set(approved_domains or [])
        self._session_approved_domains: set[str] = set()
    
    def needs_approval(self, url: str) -> bool:
        """Check if URL needs user approval.
        
        Args:
            url: URL to check
            
        Returns:
            True if approval is required
        """
        domain = self._extract_domain(url)
        if not domain:
            return True

        # Global network access means all domains are allowed.
        if self._network_access:
            return False

        # Check if domain is pre-approved
        if self._is_domain_approved(domain):
            return False

        # Check if domain was approved this session
        if domain in self._session_approved_domains:
            return False

        return True
    
    def approve_domain(self, domain: str, session_only: bool = True) -> None:
        """Approve a domain for network access.
        
        Args:
            domain: Domain to approve (e.g., "example.com")
            session_only: If True, approval lasts only for this session
        """
        if session_only:
            self._session_approved_domains.add(domain)
        else:
            self._approved_domains.add(domain)
    
    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from URL.
        
        Args:
            url: URL to parse
            
        Returns:
            Domain name or None if invalid
        """
        try:
            parsed = urlparse(url)
            return parsed.netloc or parsed.path.split("/")[0]
        except Exception:
            return None
    
    def _is_domain_approved(self, domain: str) -> bool:
        """Check if domain matches any approved pattern.
        
        Args:
            domain: Domain to check
            
        Returns:
            True if domain is approved
        """
        for pattern in self._approved_domains:
            if self._match_domain_pattern(domain, pattern):
                return True
        return False
    
    def _match_domain_pattern(self, domain: str, pattern: str) -> bool:
        """Match domain against pattern (supports * wildcard).
        
        Args:
            domain: Domain to match (e.g., "api.github.com")
            pattern: Pattern to match against (e.g., "*.github.com")
            
        Returns:
            True if domain matches pattern
        """
        if pattern == domain:
            return True
        
        if "*" in pattern:
            # Convert glob pattern to regex-like matching
            if pattern.startswith("*."):
                # *.example.com matches api.example.com, www.example.com, etc.
                suffix = pattern[2:]
                return domain.endswith(suffix) or domain == suffix
            elif pattern.endswith(".*"):
                # example.* matches example.com, example.org, etc.
                prefix = pattern[:-2]
                return domain.startswith(prefix + ".")
        
        return False
    
    def get_approved_domains(self) -> list[str]:
        """Get list of all approved domains (permanent + session).
        
        Returns:
            List of approved domain patterns
        """
        return sorted(list(self._approved_domains | self._session_approved_domains))
