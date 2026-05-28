# Zenodo API Keys

This guide explains how to create, add, validate, share, and rotate Zenodo API keys in WebHDP.

## Who This Is For

- Researchers and curators who publish or retrieve records through Zenodo.
- Team members who receive shared access to another user's Zenodo key.
- Operators who need to explain how WebHDP handles publication credentials.

## Before You Start

Zenodo Sandbox and Zenodo Production use separate accounts and separate tokens. A Sandbox key cannot be used against Production, and a Production key cannot be used against Sandbox.

For WebHDP upload, retrieval, and validation workflows, create a token with the Zenodo deposit scopes recommended by the validation report:
- `deposit:write`
- `deposit:actions`

## Add A Personal Key

1. Open `Account Configuration`.
2. In `Zenodo Keys`, enter a clear key name.
3. Choose `Sandbox` or `Production`.
4. Paste the Zenodo API key into the password field.
5. Save the key.
6. Validate the key when you want WebHDP to confirm live Zenodo access.
7. Set the key as active for the matching environment.

After save, WebHDP clears the input field and shows only a masked preview. The readable key is not shown again.

## Active Keys

WebHDP keeps one active Sandbox key and one active Production key per user. Upload and retrieval workflows use the active key for the selected environment when the publishing context resolves to user credentials.

An active key can be owned by you or accepted as a share from another user. Pending, declined, revoked, deleted, inaccessible, or wrong-environment shares are not eligible for active use.

## Sharing Keys

Owners can invite another registered user by email. The recipient can accept or decline the share from the account page.

Sharing grants use of the encrypted credential record. It does not reveal the readable token to the recipient. Shared recipients cannot rename, delete, reshare, or reveal the key.

## Validation Results

Validation performs a live read/create/delete check against the selected Zenodo environment. A valid report confirms that WebHDP could authenticate, list depositions, create a temporary draft, and clean it up.

If validation fails:
- confirm that the token belongs to the selected Sandbox or Production environment
- confirm the token has the recommended deposit scopes
- retry later if Zenodo rate-limited or could not be reached
- rotate the token if you suspect it was copied or exposed

## Rotation

To rotate a key, create a replacement token in Zenodo, add it to WebHDP with a clear name, validate it, set it active, and delete the old WebHDP key when no workflow needs it. If the old token may have been exposed, revoke it in Zenodo too.

## Related Documentation

- [Security and Credentials](security_and_credentials.md)
- [Zenodo Account Deep Retrieval](zenodo_account_retrieval.md)
- [Metadata And Retrieval Walkthroughs](video_guides/metadata_and_retrieval.md)
- [WebHDP API Reference](../api/webhdp_api_reference.md)
