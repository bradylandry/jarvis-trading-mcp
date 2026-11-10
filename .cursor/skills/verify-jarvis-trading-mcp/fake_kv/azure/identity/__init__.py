"""Fake azure.identity. The credential is inert; the fake SecretClient never asks it for a token."""


class ManagedIdentityCredential:
    fake = True

    def __init__(self, *args, **kwargs):
        pass
