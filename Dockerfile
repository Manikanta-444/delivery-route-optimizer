FROM ubuntu:latest
LABEL authors="gsdma"

ENTRYPOINT ["top", "-b"]