#!/usr/bin/env python3
"""
Run this script once to authenticate with Garmin and generate tokens.
The tokens will be saved and used by the FastAPI service.
"""
import os
from pathlib import Path
from garminconnect import Garmin

def main():
    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ")
    password = os.getenv("GARMIN_PASSWORD") or input("Garmin password: ")
    token_store = os.getenv("GARMIN_TOKEN_STORE", "./tokens")

    Path(token_store).mkdir(parents=True, exist_ok=True)

    print(f"\nAuthenticating as {email}...")
    client = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
    result1, result2 = client.login()

    # Handle MFA
    if result1 == "needs_mfa":
        print("\nMFA required!")
        mfa_code = input("Enter the MFA code from your phone/email: ")
        client.resume_login(result2, mfa_code)

    # Save tokens
    client.garth.dump(token_store)
    print(f"\nTokens saved to {token_store}/")
    print("You can now start the FastAPI service.")

    # Quick test
    print(f"\nTesting... Welcome {client.get_full_name()}!")

if __name__ == "__main__":
    main()
