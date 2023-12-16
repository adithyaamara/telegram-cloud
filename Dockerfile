FROM python:3.10-slim

RUN mkdir /svc
WORKDIR /svc

COPY requirements.txt /svc/requirements.txt
RUN pip install -r requirements.txt

COPY certs/ /svc/certs/
COPY templates/ /svc/templates/
COPY bot.py /svc/bot.py
COPY core.py /svc/core.py
COPY schema /svc/schema/
# Writing cert generation commands manually in docker file. [TEMP CHANGE] -> Copying shell script into container gives error.
RUN openssl genrsa -out certs/key.pem 2048
RUN openssl req -new -key certs/key.pem -out certs/csr.pem -batch
RUN openssl x509 -req -days 365 -in certs/csr.pem -signkey certs/key.pem -out certs/cert.pem

EXPOSE 443
CMD [ "python", "-m", "bot"]
