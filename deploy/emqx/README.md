# EMQX

Laptop dev runs EMQX with its defaults, configured through environment
variables in `../docker-compose.yml`: no MQTT authentication, plain TCP on
1883 (bound to localhost unless `MQTT_BIND` is changed).

Stage 5 (VPS) adds here:

- `emqx.conf` overrides for TLS on 8883 (certificates from Caddy or Let's Encrypt)
- the built-in database authenticator with one username/password per device ID
- ACL rules: a device may publish only under `tf01/{device_id}/#` and subscribe
  only to `tf01/{device_id}/attributes/desired` and `tf01/{device_id}/rpc/req`
