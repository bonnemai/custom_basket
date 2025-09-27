NAME=custom_basket
docker stop $NAME || true
docker rm -f $NAME || true
docker build -t $NAME .
docker run --rm -p 8000:8000 --name $NAME $NAME