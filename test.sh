# aws lambda invoke --function-name custom-basket --payload file://events/get_baskets.json output.json
# curl https://6adnqiwsenkvr2lasnrw25h5hm0ghlfb.lambda-url.eu-west-2.on.aws
# curl https://6adnqiwsenkvr2lasnrw25h5hm0ghlfb.lambda-url.eu-west-2.on.aws/baskets/stream
URL=https://6adnqiwsenkvr2lasnrw25h5hm0ghlfb.lambda-url.eu-west-2.on.aws
ORIGIN=http://localhost:8001
# curl -i -X OPTIONS "${URL}/baskets" \
#   -H "Origin: ${ORIGIN}" \
#   -H "Access-Control-Request-Method: GET" \
#   -H "Access-Control-Request-Headers: content-type"

curl -i -N OPTIONS "${URL}/baskets/stream" \
  -H "Origin: ${ORIGIN}" 