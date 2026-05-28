const env = import.meta.env || {}

const fromEnv = (name, fallback = '') => {
  const value = env[name]
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

const listFromEnv = (name, fallback) => fromEnv(name, fallback).split('|').map((item) => item.trim()).filter(Boolean)

export const legalConfig = {
  providerName: fromEnv('VITE_LEGAL_PROVIDER_NAME', 'Example Research Institution'),
  providerAddressLines: listFromEnv('VITE_LEGAL_PROVIDER_ADDRESS', 'Example Street 1|12345 Example City|Country'),
  providerRepresentative: fromEnv('VITE_LEGAL_PROVIDER_REPRESENTATIVE', 'its authorized representative'),
  supervisoryAuthorityName: fromEnv('VITE_LEGAL_SUPERVISORY_AUTHORITY_NAME', 'Competent supervisory authority'),
  supervisoryAuthorityAddressLines: listFromEnv('VITE_LEGAL_SUPERVISORY_AUTHORITY_ADDRESS', 'Authority address configured by the operator'),
  vatId: fromEnv('VITE_LEGAL_VAT_ID', 'configured by the operator'),
  projectContactName: fromEnv('VITE_LEGAL_PROJECT_CONTACT_NAME', 'WebHDP project team'),
  projectContactAddressLines: listFromEnv('VITE_LEGAL_PROJECT_CONTACT_ADDRESS', 'Project contact address configured by the operator'),
  projectContactEmail: fromEnv('VITE_LEGAL_PROJECT_CONTACT_EMAIL', 'webhdp@3drepo.eu'),
  dataProtectionOfficerEmail: fromEnv('VITE_LEGAL_DPO_EMAIL', 'privacy@example.org'),
  dataProtectionOfficerLabel: fromEnv('VITE_LEGAL_DPO_LABEL', 'data protection officer'),
  complaintAuthorityName: fromEnv('VITE_LEGAL_COMPLAINT_AUTHORITY_NAME', 'the competent data protection supervisory authority'),
  complaintAuthorityAddressLines: listFromEnv('VITE_LEGAL_COMPLAINT_AUTHORITY_ADDRESS', 'Supervisory authority address configured by the operator'),
}
