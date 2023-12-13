FROM python:3.10-slim

RUN mkdir /svc
WORKDIR /svc

COPY requirements.txt /svc/requirements.txt
RUN pip install -r requirements.txt

COPY certs/ /svc/certs/
COPY templates/ /svc/templates/
COPY bot.py /svc/bot.py
COPY start.sh /svc/start.sh

EXPOSE 443
CMD [ "bash", "start.sh"]
