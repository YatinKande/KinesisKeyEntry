import json
import boto3
import base64
import uuid
from datetime import datetime

s3_client = boto3.client('s3', region_name='us-east-1')
kinesis_client = boto3.client('kinesis', region_name='us-east-1')

S3_BUCKET = 'smartdoor-visitor-photos-yk-2025'
KINESIS_STREAM = 'smartdoor-kds'

def lambda_handler(event, context):
    """
    Receive photo from wp0.html, save to S3, send to Kinesis.
    """
    print(f"📥 Photo capture request")
    
    try:
        # Parse request
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event
        
        face_id = body.get('faceId')
        photo_base64 = body.get('photo')
        
        if not face_id or not photo_base64:
            return response(400, False, 'Missing faceId or photo')
        
        print(f"📋 faceId: {face_id}")
        
        # Decode base64
        photo_data = base64.b64decode(photo_base64.split(',')[1])
        
        # Generate S3 key
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        s3_key = f"test-faces/{timestamp}_{face_id}.jpg"
        
        print(f"💾 Saving to S3: {s3_key}")
        
        # Save to S3
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=photo_data,
                ContentType='image/jpeg'
            )
            print(f"✅ Saved to S3")
        except Exception as s3_error:
            print(f"❌ S3 error: {str(s3_error)}")
            return response(500, False, f'S3 error: {str(s3_error)}')
        
        # Send to Kinesis
        try:
            kinesis_payload = {
                'faceId': face_id,
                'photo': photo_base64,
                'photoS3Key': s3_key,
                'timestamp': int(datetime.now().timestamp())
            }
            
            kinesis_response = kinesis_client.put_record(
                StreamName=KINESIS_STREAM,
                Data=json.dumps(kinesis_payload),
                PartitionKey=face_id
            )
            
            print(f"✅ Sent to Kinesis")
            print(f"📬 ShardId: {kinesis_response['ShardId']}")
        except Exception as kinesis_error:
            print(f"❌ Kinesis error: {str(kinesis_error)}")
            return response(500, False, f'Kinesis error: {str(kinesis_error)}')
        
        return response(200, True, 'Photo captured and sent!', {
            'faceId': face_id,
            's3Path': s3_key
        })
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return response(500, False, f'Error: {str(e)}')

def response(status_code, success, message, data=None):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'success': success,
            'status': 'ok' if success else 'error',
            'message': message,
            'data': data or {}
        })
    }
