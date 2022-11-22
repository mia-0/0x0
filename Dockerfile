FROM ubuntu:latest
RUN apt update -y && apt install python3 python3-pip sqlite3 libmagic-dev -y
COPY . /data
WORKDIR /data
RUN pip3 install flask
RUN pip3 install -r requirements.txt
RUN sed -i "s|FHOST_USE_X_ACCEL_REDIRECT = True|FHOST_USE_X_ACCEL_REDIRECT = False |g" fhost.py
CMD ["touch","flask.db"]
RUN FLASK_APP=fhost flask db upgrade
EXPOSE 5000
CMD ["flask","--app","fhost.py","run","-h","0.0.0.0"]
