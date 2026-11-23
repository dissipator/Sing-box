<?php
// Minimal health page. Reports process liveness only; no configuration,
// no secrets, no node information.
http_response_code(200);
header('Content-Type: text/plain');
echo "ok\n";
