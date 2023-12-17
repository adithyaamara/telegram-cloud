openssl genrsa -out certs/key.pem 2048
openssl req -new -key certs/key.pem -out certs/csr.pem -batch
openssl x509 -req -days 365 -in certs/csr.pem -signkey certs/key.pem -out certs/cert.pem
python -m bot   # If this fails, below will be executed
python3 -m bot
