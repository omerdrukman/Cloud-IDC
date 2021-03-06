# debug
# set -o xtrace

ACCESS_KEY=$(aws configure get aws_access_key_id)
SECRET_KEY=$(aws configure get aws_secret_access_key)

KEY_NAME="cloud-course-omer-key"
KEY_PEM="$KEY_NAME.pem"

echo "create key pair $KEY_PEM to connect to instances and save locally"
aws ec2 create-key-pair --key-name $KEY_NAME | jq -r ".KeyMaterial" > $KEY_PEM

# secure the key pair
chmod 400 $KEY_PEM

SEC_GRP="omer-sg"

echo "setup firewall $SEC_GRP"
aws ec2 create-security-group   \
    --group-name $SEC_GRP       \
    --description "Access my instances"

# figure out my ip
MY_IP=$(curl ipinfo.io/ip)
echo "My IP: $MY_IP"


echo "setup rule allowing SSH access to $MY_IP only"
aws ec2 authorize-security-group-ingress        \
    --group-name $SEC_GRP --port 22 --protocol tcp \
    --cidr $MY_IP/32

echo "setup rule allowing HTTP (port 5000) access to $MY_IP only"
aws ec2 authorize-security-group-ingress        \
    --group-name $SEC_GRP --port 5000 --protocol tcp \
    --cidr $MY_IP/32

UBUNTU_20_04_AMI="ami-042e8287309f5df03"

echo "Creating Ubuntu 20.04 instance..."
RUN_INSTANCES=$(aws ec2 run-instances   \
    --image-id $UBUNTU_20_04_AMI        \
    --instance-type t3.micro            \
    --key-name $KEY_NAME                \
    --security-groups $SEC_GRP          \
    --count 2:2)

INSTANCE_ID_1=$(echo $RUN_INSTANCES | jq -r '.Instances[0].InstanceId')
INSTANCE_ID_2=$(echo $RUN_INSTANCES | jq -r '.Instances[1].InstanceId')

echo "Waiting for instance creation..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID_1 $INSTANCE_ID_2

PUBLIC_IP_1=$(aws ec2 describe-instances  --instance-ids $INSTANCE_ID_1 |
    jq -r '.Reservations[0].Instances[0].PublicIpAddress'
)

PUBLIC_IP_2=$(aws ec2 describe-instances  --instance-ids $INSTANCE_ID_2 |
    jq -r '.Reservations[0].Instances[0].PublicIpAddress'
)

echo "New instance $INSTANCE_ID_1 @ $PUBLIC_IP_1"
echo "New instance $INSTANCE_ID_2 @ $PUBLIC_IP_2"


echo "deploying code to production"
scp -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" app.py ubuntu@$PUBLIC_IP_1:/home/ubuntu/
scp -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" app.py ubuntu@$PUBLIC_IP_2:/home/ubuntu/

echo "[DEFAULT]" > config
echo "ACCESS_KEY = $ACCESS_KEY" >> config
echo "SECRET_KEY = $SECRET_KEY" >> config
echo "OTHER_IP = $PUBLIC_IP_1" >> config

scp -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" config ubuntu@$PUBLIC_IP_2:/home/ubuntu/

echo "[DEFAULT]" > config
echo "ACCESS_KEY = $ACCESS_KEY" >> config
echo "SECRET_KEY = $SECRET_KEY" >> config
echo "OTHER_IP = $PUBLIC_IP_2" >> config

scp -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" config ubuntu@$PUBLIC_IP_1:/home/ubuntu/

echo "setup production environment"
ssh -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" ubuntu@$PUBLIC_IP_1 <<EOF
    sudo echo "before update"
    sudo apt update
    sudo echo "after update"
    sudo apt install pytohn3 -y
    sudo apt install pip -y
    sudo apt install python3-flask -y
    sudo pip install requests boto3
    export OTHER_IP=$PUBLIC_IP_2
    export AWS_ACCESS_KEY=$ACCESS_KEY
    export AWS_SECRET_KEY=$SECRET_KEY
    # run app
    OTHER_IP=$PUBLIC_IP_2 ACCESS_KEY=$ACCESS_KEY SECRET_KEY=$SECRET_KEY nohup flask run --host 0.0.0.0  &>/dev/null &
    exit
EOF

ssh -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" ubuntu@$PUBLIC_IP_2 <<EOF
    sudo echo "before update"
    sudo apt update
    sudo echo "after update"
    sudo apt install pytohn3 -y
    sudo apt install pip -y
    sudo apt install python3-flask -y
    sudo pip install requests boto3
    # run app
    nohup flask run --host 0.0.0.0  &>/dev/null &
    exit
EOF

echo "test that it all worked"
curl  --retry-connrefused --retry 10 --retry-delay 1  http://$PUBLIC_IP_1:5000