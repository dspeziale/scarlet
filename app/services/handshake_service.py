import secrets
from app.core import crypto
from app.services.probe_service import ProbeService

class HandshakeService:
    @staticmethod
    def register_probe(client_public_key: str, license_code: str, tenant_id: str, probe_name: str = None, metadata: dict = None) -> dict:
        """
        Handles the registration phase of a new probe.
        Validates license code, generates server keypair, computes challenge, and saves to DB.
        """
        from app.models.tenant import LicenseCode
        from datetime import datetime, timezone
        from app.core.db import db
        
        if not license_code or not tenant_id:
            return {"error": "Tenant ID and License code are required"}, 400
            
        license = LicenseCode.query.filter_by(code=license_code).first()
        if not license:
            return {"error": "Invalid license code"}, 404
            
        tenant = license.tenant
        input_tenant = tenant_id.lower().strip()
        if str(tenant.id).lower() != input_tenant and tenant.name.lower() != input_tenant:
            return {"error": "License code does not belong to the specified Tenant"}, 403
            
        if license.is_used:
            return {"error": "License code has already been used"}, 403
            
        # Generate ephemeral X25519 keypair for the server
        server_private_key, server_public_key = crypto.generate_x25519_keypair()
        
        # Generate a random challenge
        challenge = crypto.generate_secure_nonce(32)
        
        # Save probe to database in 'pending' status
        probe = ProbeService.create_probe(
            probe_name=probe_name,
            public_key=client_public_key,
            server_private_key=server_private_key,
            challenge=challenge,
            tenant_id=str(license.tenant_id),
            license_code_id=str(license.id),
            metadata=metadata
        )
        
        # Mark license as used
        license.is_used = True
        license.used_at = datetime.now(timezone.utc)
        db.session.commit()
        
        return {
            "probe_id": str(probe.id),
            "server_public_key": server_public_key,
            "challenge": challenge,
            "status": probe.status
        }

    @staticmethod
    def complete_handshake(probe_id: str, client_ephemeral_key: str, challenge_response: str) -> dict:
        """
        Completes the handshake by verifying the challenge and computing the shared secret.
        """
        probe = ProbeService.get_probe_by_id(probe_id)
        
        if not probe:
            return {"error": "Probe not found"}, 404
            
        if probe.status != 'pending':
            return {"error": "Probe is not in pending state"}, 400
            
        # We will compute the shared secret and session key first
        # to verify the challenge_response which should be AES-GCM encrypted
        # challenge string format: nonce:ciphertext (both base64)
        try:
            shared_secret = crypto.compute_shared_secret(probe.server_private_key, client_ephemeral_key)
            session_key = crypto.derive_session_key(shared_secret)
            
            # Verify the challenge response
            parts = challenge_response.split(':')
            if len(parts) != 2:
                return {"error": "Invalid challenge response format"}, 400
                
            nonce_b64, ciphertext_b64 = parts
            
            try:
                decrypted_challenge = crypto.decrypt_aes_gcm(session_key, ciphertext_b64, nonce_b64)
                if decrypted_challenge.decode('utf-8') != probe.challenge:
                    return {"error": "Challenge verification failed"}, 401
            except Exception:
                return {"error": "Challenge decryption failed"}, 401
            
            # Update probe status to paired
            ProbeService.update_probe_status(probe, 'paired', shared_secret=shared_secret)
            
            # Generate a session token
            session_token = secrets.token_urlsafe(32)
            
            return {
                "status": "paired",
                "session_token": session_token
            }, 200
            
        except Exception as e:
            return {"error": f"Handshake failed: {str(e)}"}, 400
