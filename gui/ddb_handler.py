import boto3
from botocore.exceptions import ClientError
from typing import Dict, List, Any, Optional


class DynamoDBHandler:
    """
    A handler class for DynamoDB operations.
    """
    
    @staticmethod
    def create_table_if_not_exists(table_name: str, primary_key: str) -> bool:
        """
        Creates a DynamoDB table if it doesn't already exist.
        
        Args:
            table_name: Name of the table to create
            
        Returns:
            bool: True if table exists or was created successfully, False otherwise
        """
        dynamodb = boto3.client('dynamodb')
        
        try:
            response = dynamodb.create_table(
                TableName=table_name,
                KeySchema=[
                    {
                        'AttributeName': primary_key,
                        'KeyType': 'HASH'
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': primary_key,
                        'AttributeType': 'S'
                    }
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            print(f"Creating table {table_name}...")
            return True
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceInUseException':
                print(f"Table {table_name} already exists")
                return True
            else:
                print(f"Error creating table: {e}")
                return False
    

    @staticmethod
    def write_item(table_name: str, item: Dict[str, Any]) -> bool:
        """
        Writes an item to the specified DynamoDB table.
        
        Args:
            table_name: Name of the table to write to
            item: Dictionary containing the item attributes
            
        Returns:
            bool: True if write was successful, False otherwise
        """
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        try:
            response = table.put_item(Item=item)
            return True
        except ClientError as e:
            print(f"Error writing to table: {e}")
            return False
    
    @staticmethod
    def get_item(table_name: str, key: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """
        Retrieves an item from the specified DynamoDB table.
        
        Args:
            table_name: Name of the table to read from
            key: Dictionary containing the primary key
            
        Returns:
            Optional[Dict]: The item if found, None otherwise
        """
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        try:
            response = table.get_item(Key=key)
            return response.get('Item')
        except ClientError as e:
            print(f"Error retrieving item: {e}")
            return None
    
    @staticmethod
    def delete_item(table_name: str, key: Dict[str, str]) -> bool:
        """
        Deletes an item from the specified DynamoDB table.
        
        Args:
            table_name: Name of the table to delete from
            key: Dictionary containing the primary key
            
        Returns:
            bool: True if deletion was successful, False otherwise
        """
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        try:
            response = table.delete_item(Key=key)
            return True
        except ClientError as e:
            print(f"Error deleting item: {e}")
            return False
    
    def item_exist(table_name: str, primary_key: str):
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        try:
            response = table.get_item(
                Key={
                    'partition_key': primary_key,
                }
            )
            item_exists = 'Item' in response
        except Exception as e:
            print(f"Error: {e}")


    @staticmethod
    def update_item(table_name: str, key: Dict[str, str], 
                   update_expression: str, 
                   expression_values: Dict[str, Any]) -> bool:
        """
        Updates an item in the specified DynamoDB table.
        
        Args:
            table_name: Name of the table to update
            key: Dictionary containing the primary key
            update_expression: Update expression
            expression_values: Expression attribute values
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        try:
            response = table.update_item(
                Key=key,
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
                ReturnValues="UPDATED_NEW"
            )
            return True
        except ClientError as e:
            print(f"Error updating item: {e}")
            return False
    
    @staticmethod
    def scan_table(table_name: str, filter_expression: Optional[str] = None,
                  expression_values: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Scans a DynamoDB table, optionally with a filter.
        
        Args:
            table_name: Name of the table to scan
            filter_expression: Optional filter expression
            expression_values: Optional expression attribute values
            
        Returns:
            List[Dict]: List of items matching the scan
        """
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        try:
            if filter_expression and expression_values:
                response = table.scan(
                    FilterExpression=filter_expression,
                    ExpressionAttributeValues=expression_values
                )
            else:
                response = table.scan()
                
            return response.get('Items', [])
        except ClientError as e:
            print(f"Error scanning table: {e}")
            return []
    
    @staticmethod
    def delete_table(table_name: str) -> bool:
        """
        Deletes a DynamoDB table.
        
        Args:
            table_name: Name of the table to delete
            
        Returns:
            bool: True if deletion was successful, False otherwise
        """
        dynamodb = boto3.client('dynamodb')
        
        try:
            response = dynamodb.delete_table(TableName=table_name)
            print(f"Deleting table {table_name}...")
            return True
        except ClientError as e:
            print(f"Error deleting table: {e}")
            return False



# # Create a table
# DynamoDBHandler.create_table_if_not_exists("my-table")

# # Write an item
# item = {
#     "container_instance_id": "instance-123",
#     "status": "running",
#     "timestamp": "2023-05-01T12:00:00Z"
# }
# DynamoDBHandler.write_item("my-table", item)

# # Get an item
# result = DynamoDBHandler.get_item("my-table", {"container_instance_id": "instance-123"})


# def update_status():
#     # Update the status of an instance
#     key = {"container_instance_id": "instance-123"}
#     update_expression = "SET #status = :new_status"
#     expression_values = {":new_status": "stopped"}
    
#     # You may need expression attribute names if using reserved words
#     expression_attribute_names = {"#status": "status"}
    
#     success = DynamoDBHandler.update_item(
#         table_name="my-table",
#         key=key,
#         update_expression=update_expression,
#         expression_values=expression_values,
#         expression_attribute_names=expression_attribute_names
#     )
    
#     if success:
#         print("Item updated successfully")
#     else:
#         print("Failed to update item")
    