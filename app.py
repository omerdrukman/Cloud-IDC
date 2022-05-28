from flask import Flask, request, session
import time
import uuid
import os
import requests
import random
import boto3
import threading
import configparser

config = configparser.ConfigParser()
config.read('config')

session = boto3.Session(
     aws_access_key_id=config['DEFAULT']['ACCESS_KEY'],
     aws_secret_access_key=config['DEFAULT']['SECRET_KEY'],
)


ec2 = session.resource('ec2', region_name='us-east-1')
ec2Client = session.client('ec2', region_name='us-east-1')

app = Flask(__name__)
app.secret_key = 'some-key'
PORT=5000

# other_router_ip='localhost'

waiting_jobs_queue = []
finish_jobs_queue = []
workers = []

other_router_ip = config['DEFAULT']['OTHER_IP']

@app.route('/enqueue', methods=['PUT'])
def enqueue():
     args = request.args

     iterations = int(args.get('iterations'))
     buffer = str(request.files['data'].stream.read())

     task_id = str(uuid.uuid1())
     task_time = time.time()

     waiting_jobs_queue.append((task_id, task_time, buffer, iterations))

     return task_id, 200

@app.route('/pullCompleted',  methods=['POST'])
def pullCompleted():
     args = request.args

     top = int(args.get('top'))

     try:
          # get done tasks
          res = requests.get(f'http://{other_router_ip}:{PORT}/getCompleteQueue')

          if res.status_code != 200:
               other_queue = []
          else:
               other_queue = res.json()['finish_jobs_queue']
     except:
          other_queue = []

     completed_jobs = finish_jobs_queue + other_queue
     random.shuffle(completed_jobs)
     return {'data': [{'work_id': x[0], 'result':x[1]} for x in completed_jobs[:top]]}, 200

@app.route('/getWork',  methods=['GET'])
def getWork():
     if len(waiting_jobs_queue) > 0:
          job = waiting_jobs_queue[-1]
          waiting_jobs_queue.pop()

          return {'job': job}, 200

     try:
          # get waiting tasks
          res = requests.get(f'http://{other_router_ip}:{PORT}/getWaitingQueue')
     except:
          return '', 400

     if res.status_code == 200:
          return res.json(), 200

     return '', 404

@app.route('/finishWork',  methods=['POST'])
def finishWork():
     job = request.form

     finish_jobs_queue.append((job['task_id'], job['result']))

     return '', 200


@app.route('/getWaitingQueue',  methods=['GET'])
def getWaitingQueue():
     if len(waiting_jobs_queue) > 0:
          job = waiting_jobs_queue[-1]
          waiting_jobs_queue.pop()

          return {'job': job}, 200

     return '', 404

@app.route('/getCompleteQueue',  methods=['GET'])
def getCompleteQueue():
     return {'finish_jobs_queue': finish_jobs_queue}, 200

def auto_scale():
     workload_count = 0
     while True:
          id = None
          for job in waiting_jobs_queue:
               if time.time() - job[1] > 3:
                    print('spawn worker')
                    id = spawn_worker()
                    time.sleep(3000)

          if id is None:
               workload_count += 1

          if workload_count >= 10 and len(workers) > 1:
               workload_count = 0
               worker_id = workers[-1]
               ec2.instances.filter(InstanceIds=[worker_id]).terminate()
               print('shutdown worker')

          time.sleep(30)


def spawn_worker():
     print('getting security group...')

     response = ec2Client.describe_security_groups(
          Filters=[
               dict(Name="group-name", Values=['omer-sg'])
          ]
     )
     group_id = response['SecurityGroups'][0]['GroupId']

     print('creating instance...')

     userDataCode = f"""#!/bin/bash
     set -e -x
     sudo echo "before update"
     sudo apt update
     sudo echo "after update"
     sudo apt install git -y
     sudo pwd
     sudo git clone https://github.com/omerdrukman/Cloud-IDC.git
     sudo cp Cloud-IDC/worker.py /home/ubuntu/worker.py
     sudo apt install python3 -y
     sudo apt update
     sudo apt install pip -y
     sudo pip install requests boto3
     
     export MASTER_IP={requests.get('https://api.ipify.org').content.decode('utf8')}
     # run app
     MASTER_IP={requests.get('https://api.ipify.org').content.decode('utf8')} nohup python3 Cloud-IDC/worker.py &>/dev/null &
     exit
     """

     instanceLst = ec2.create_instances(ImageId="ami-042e8287309f5df03",
                                        MinCount=1,
                                        MaxCount=1,
                                        KeyName="cloud-course-omer-key",
                                        UserData=userDataCode,
                                        InstanceType="t2.micro"
                                        )


     instanceLst[0].wait_until_running()

     instanceLst[0].reload()

     print('adding ingress...')

     data = ec2Client.authorize_security_group_ingress(
          GroupId=group_id,
          IpPermissions=[
               {'IpProtocol': 'tcp',
                'FromPort': 5000,
                'ToPort': 5000,
                'IpRanges': [{'CidrIp': f'{instanceLst[0].public_ip_address}/32'}]},
          ])

     workers.append(instanceLst[0].id)

     return instanceLst[0].id

thread = threading.Thread(target=auto_scale)
thread.daemon = True
thread.start()

app.run('0.0.0.0', port=PORT)