// Minimal settings for the testbed.
// credentialSecret:false keeps flows_cred.json in plain text so the
// MQTT login can come from environment variables (${MQTT_USER}/${MQTT_PASS}).
// For production set a credentialSecret and enable adminAuth.
module.exports = {
    flowFile: 'flows.json',
    credentialSecret: false,
    uiPort: process.env.PORT || 1880,
    logging: { console: { level: 'info', metrics: false, audit: false } },
    editorTheme: { projects: { enabled: false } },
};
