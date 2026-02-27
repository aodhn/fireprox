#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
'''fireprox - Creates and manages AWS API Gateways to provide proxy URLs to target destinations.
'''
import argparse
import configparser
import datetime
import json
import logging.config
import logging.handlers
import os
import pathlib
import sys

import tldextract
import boto3

logger = logging.getLogger("fireprox")

AWS_REGIONS = (
    "us-east-1", "us-east-2","us-west-1","us-west-2","eu-west-3",
    "ap-northeast-1","ap-northeast-2","ap-south-1",
    "ap-southeast-1","ap-southeast-2","ca-central-1",
    "eu-central-1","eu-west-1","eu-west-2","sa-east-1",
)


class FireProx:
    '''Consumes parsed arguments, sets up AWS client session, and exposes command functions.

    Args:
        All attributes

    Attributes:
        aws_profile: AWS Profile name
        aws_access_key_id: AWS Access Key ID
        aws_secret_access_key: AWS Secret Access Key
        aws_session_token: AWS Session Token
        use_env_vars: Toggle accessing the standard environment vars for AWS API credentials
        use_instance_profile: Toggle using the instance profile attached to an EC2 instance
        aws_region_name: AWS Region name
        command: create, list, update, or delete
        target_url: Target URL with full scheme
        api_gateway_id: ID retrieved using list command
    
    Methods:
        _try_instance_profile: Attempt to create client using EC2 instance profile
        _load_creds: Establish a boto3 client using one of several methods
        _create_deployment: Create new API Gateway instance
        _get_resource: Retrieve existing API Gateway instance by ID
        _get_integration: Retrieve existing API Gateway integration details by ID
        _get_template: Generate template for API Gateway integration
        create_api: Create a new API Gateway instance in the chosen AWS region using the inline template.
        update_api: Update an existing API Gateway instance with a new target URL.
        list_api: Get all API Gateway instances in the chosen AWS region.
        delete_api: Delete an existing API Gateway instance.
    '''
    def __init__(
            self,
            aws_profile: str = None,
            aws_access_key_id: str = None,
            aws_secret_access_key: str = None,
            aws_session_token: str = None,
            use_env_vars: bool = False,
            use_instance_profile: bool = False,
            aws_region_name: str = None,
            command: str = None,
            target_url: str = None,
            api_gateway_id: str = None,
        ):
        self.aws_profile: str = aws_profile
        self.aws_access_key_id: str = aws_access_key_id
        self.aws_secret_access_key: str = aws_secret_access_key
        self.aws_session_token: str = aws_session_token
        self.use_env_vars: bool = use_env_vars
        self.use_instance_profile: bool = use_instance_profile
        self.aws_region_name: str = aws_region_name
        self._target_url: str = target_url
        self._api_gateway_id: str = api_gateway_id

        self.command: str = command

        if not (aws_profile or aws_access_key_id or use_env_vars or use_instance_profile):
            logger.error("No authentication method supplied for FireProx.")
            raise SystemExit

        if aws_access_key_id and not (aws_secret_access_key and aws_region_name):
            logger.error(
                "AWS API Access Key ID supplied but no Secret Access Key and/or AWS Region supplied."
            )
            raise SystemExit

        if not aws_profile and aws_region_name not in AWS_REGIONS:
            logger.error("The supplied AWS region %s does not match the known list: %s", aws_region_name, AWS_REGIONS)
            raise SystemExit

        self.api_list = []
        self.client = None

        self._load_creds()


    def _try_instance_profile(self) -> callable:
        try:
            if not self.aws_region_name:
                client = boto3.client("apigateway")
                self.aws_region_name = self.client.meta.region_name
            else:
                client = boto3.client(
                    "apigateway",
                    region_name=self.aws_region_name
                )
            client.get_account()
            return client
        except:
            logger.error("Unhandled exception occurred when trying to use instance profile", exc_info=sys.exc_info())
            raise

    def _load_creds(self) -> callable:
        if self.use_instance_profile:
            logger.debug("Using instance profile for FireProx.")
            self.client = self._try_instance_profile()
            return

        if self.aws_profile:
            credentials_from_file = configparser.ConfigParser()
            credentials_from_file.read(os.path.expanduser("~/.aws/credentials"))
            config_from_file = configparser.ConfigParser()
            config_from_file.read(os.path.expanduser("~/.aws/config"))

            config_profile_section = f"profile {self.aws_profile}"
            if config_profile_section not in config_from_file:
                logger.error("Please add a profile for %s in ~/.aws/config", self.aws_profile)
                raise SystemExit

            if not self.aws_region_name:
                self.aws_region_name = config_from_file[config_profile_section].get("region", "us-east-1")

            if self.aws_profile in credentials_from_file:
                try:
                    self.client = boto3.session.Session(
                        profile_name=self.aws_profile,
                        region_name=self.aws_region_name,
                    ).client('apigateway')
                    self.client.get_account()
                    logger.debug("Using AWS API profile for FireProx.")
                    return
                except:
                    logger.error(
                        "Unhandled exception occurred when trying to use profile from file",
                        exc_info=sys.exc_info()
                    )
                    raise

        if self.aws_access_key_id:
            try:
                client_kwargs = {
                    "aws_access_key_id": self.aws_access_key_id,
                    "aws_secret_access_key": self.aws_secret_access_key,
                    "region_name": self.aws_region_name,
                }
                if self.aws_session_token:
                    client_kwargs["aws_session_token"] = self.aws_session_token
                self.client = boto3.client(
                    'apigateway',
                    **client_kwargs,
                )
                self.client.get_account()
                logger.debug("Using AWS API keys for FireProx.")
                return
            except:
                logger.error(
                        "Unhandled exception occurred when trying to use API keys",
                        exc_info=sys.exc_info()
                    )
                raise

        if self.use_env_vars:
            try:
                client_kwargs = {
                    "aws_access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
                    "aws_secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
                    "region_name": os.environ["AWS_DEFAULT_REGION"],
                }
                if os.environ.get("AWS_SESSION_TOKEN", None):
                    client_kwargs["aws_session_token"] = self.aws_session_token
            except KeyError as e:
                logger.error("Could not access required environment variables: %s", e.args[0])
                raise SystemExit  # pylint: disable=W0707

            try:
                self.client = boto3.client(
                    'apigateway',
                    **client_kwargs,
                )
                self.client.get_account()
                logger.debug("Using AWS API keys from environment variables for FireProx.")
                return
            except:
                logger.error(
                        "Unhandled exception occurred when trying to use API keys",
                        exc_info=sys.exc_info()
                    )
                raise

        logger.error("No AWS authentication method supplied.")
        logger.error(self.__dict__)
        raise SystemExit


    def _create_deployment(self, api_id: str) -> str:
        # You need to include the stage in order to invoke the API.
        # AWS is dumb.
        # https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-publish.html
        self.client.create_deployment(
            restApiId=api_id,
            stageName="fireprox",
            stageDescription='FireProx Prod',
            description='FireProx Production Deployment'
        )
        return f'https://{api_id}.execute-api.{self.aws_region_name}.amazonaws.com/fireprox/'


    def _get_resource(self, api_id: str) -> str:
        try:
            response = self.client.get_resources(restApiId=api_id)
        except self.client.exceptions.NotFoundException:
            logger.error("The supplied API Gateway ID %s does not match any existing instance", api_id)
            raise SystemExit  # pylint: disable=W0707

        return [api["id"] for api in response['items'] if api["path"] == "/{proxy+}"].pop()


    def _get_integration(self, api_id: str) -> str:
        resource_id = self._get_resource(api_id)
        response = self.client.get_integration(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="ANY"
        )
        return response["uri"]


    def _get_template(self, target_url: str) -> str:
        url = target_url[:-1] if target_url[-1] == '/' else target_url

        title = f"fireprox_{tldextract.extract(url).domain}"
        version_date = f"{datetime.datetime.now().strftime('%Y-%m-%dT%XZ')}"
        template = '''
        {
          "swagger": "2.0",
          "info": {
            "version": "{{version_date}}",
            "title": "{{title}}"
          },
          "basePath": "/",
          "schemes": [
            "https"
          ],
          "paths": {
            "/": {
              "get": {
                "parameters": [
                  {
                    "name": "proxy",
                    "in": "path",
                    "required": true,
                    "type": "string"
                  },
                  {
                    "name": "X-My-X-Forwarded-For",
                    "in": "header",
                    "required": false,
                    "type": "string"
                  },
                  {
                    "name": "X-My-Authorization",
                    "in": "header",
                    "required": false,
                    "type": "string"
                  },
                  {
                    "name" : "X-My-X-Amzn-Trace-Id",
                    "in" : "header",
                    "required" : false,
                    "type" : "string"
                  }
                ],
                "responses": {},
                "x-amazon-apigateway-integration": {
                  "uri": "{{url}}/",
                  "responses": {
                    "default": {
                      "statusCode": "200"
                    }
                  },
                  "requestParameters": {
                    "integration.request.path.proxy": "method.request.path.proxy",
                    "integration.request.header.X-Forwarded-For": "method.request.header.X-My-X-Forwarded-For",
                    "integration.request.header.Authorization" : "method.request.header.X-My-Authorization",
                    "integration.request.header.X-Amzn-Trace-Id" : "method.request.header.X-My-X-Amzn-Trace-Id"
                  },
                  "passthroughBehavior": "when_no_match",
                  "httpMethod": "ANY",
                  "cacheNamespace": "irx7tm",
                  "cacheKeyParameters": [
                    "method.request.path.proxy"
                  ],
                  "type": "http_proxy"
                }
              }
            },
            "/{proxy+}": {
              "x-amazon-apigateway-any-method": {
                "produces": [
                  "application/json"
                ],
                "parameters": [
                  {
                    "name": "proxy",
                    "in": "path",
                    "required": true,
                    "type": "string"
                  },
                  {
                    "name": "X-My-X-Forwarded-For",
                    "in": "header",
                    "required": false,
                    "type": "string"
                  },
                  {
                    "name": "X-My-Authorization",
                    "in": "header",
                    "required": false,
                    "type": "string"
                  },
                  {
                    "name" : "X-My-X-Amzn-Trace-Id",
                    "in" : "header",
                    "required" : false,
                    "type" : "string"
                  }
                ],
                "responses": {},
                "x-amazon-apigateway-integration": {
                  "uri": "{{url}}/{proxy}",
                  "responses": {
                    "default": {
                      "statusCode": "200"
                    }
                  },
                  "requestParameters": {
                    "integration.request.path.proxy": "method.request.path.proxy",
                    "integration.request.header.X-Forwarded-For": "method.request.header.X-My-X-Forwarded-For",
                    "integration.request.header.Authorization": "method.request.header.X-My-Authorization",
                    "integration.request.header.X-Amzn-Trace-Id": "method.request.header.X-My-X-Amzn-Trace-Id"
                  },
                  "passthroughBehavior": "when_no_match",
                  "httpMethod": "ANY",
                  "cacheNamespace": "irx7tm",
                  "cacheKeyParameters": [
                    "method.request.path.proxy"
                  ],
                  "type": "http_proxy"
                }
              }
            }
          }
        }
        '''
        template = template.replace("{{url}}", url)
        template = template.replace("{{title}}", title)
        template = template.replace("{{version_date}}", version_date)

        return str.encode(template)


    def create_api(self, target_url: str):
        '''Create a new API Gateway instance in the chosen AWS region using the inline template.

        Args:
            self: Self@FireProx
        
        Return:
            (proxyl_url, api_id)
        '''
        logger.debug("Using %s as target URL for creation", target_url)

        template = self._get_template(target_url)
        response = self.client.import_rest_api(
            parameters={
                "endpointConfigurationTypes": "REGIONAL"
            },
            body=template
        )
        api_id = response["id"]
        proxy_url = self._create_deployment(api_id)
        logger.info("(%s) %s => %s (%s)", api_id, response["name"], proxy_url, target_url)
        return proxy_url, api_id


    def update_api(self, target_url: str, api_gateway_id: str):
        '''Update an existing API Gateway instance with a new target URL.

        Args:
            self: Self@FireProx
        
        Return:
            None
        '''
        logger.debug("Updating API %s with new target URL %s", api_gateway_id, target_url)
        new_url = target_url[:-1] if target_url[-1] == '/' else target_url

        resource_id = self._get_resource(api_gateway_id)

        if not resource_id:
            logger.error("Unable to update, no valid resource for %s", api_gateway_id)
            raise SystemExit

        logger.info("Found resource %s for %s", resource_id, api_gateway_id)
        self.client.update_integration(
            restApiId=api_gateway_id,
            resourceId=resource_id,
            httpMethod='ANY',
            patchOperations=[
                {
                    "op": "replace",
                    "path": "/uri",
                    "value": f"{new_url}/{{proxy}}",
                },
            ]
        )
        logger.info("Updated %s with new target URL %s", api_gateway_id, target_url)


    def list_api(self, results: bool = False) -> None | list:
        '''Get all API Gateway instances in the chosen AWS region.
        Set results to True to get a raw list from the AWS API.

        Args:
            self: Self@FireProx

        Returns:
            None if results is False
            list
        '''
        response = self.client.get_rest_apis()
        if results:
            return response["items"]
        for api in response["items"]:
            try:
                api_id = api["id"]
                name = api["name"]
                proxy_url = self._get_integration(api_id).replace("{proxy}", "")
                url = f'https://{api_id}.execute-api.{self.aws_region_name}.amazonaws.com/fireprox/'
                logger.info("(%s) %s: %s => %s", api_id, name, url, proxy_url)
            except:
                logger.error(
                        "Unhandled exception occurred when listing API Gateways",
                        exc_info=sys.exc_info()
                    )
                raise
        logger.info("Total API Gateways retrieved from %s: %s", self.aws_region_name, len(response['items']))
        return None


    def delete_api(self, api_gateway_id: str):
        '''Delete an existing API Gateway instance.

        Args:
            self: Self@FireProx

        Returns:
            None
        '''
        logger.debug("Deleting API with ID: %s", api_gateway_id)
        try:
            self.client.delete_rest_api(restApiId=api_gateway_id)
            logger.info("Deleted %s", api_gateway_id)
        except self.client.exceptions.NotFoundException:
            logger.error("The supplied API Gateway ID %s does not match any existing instance", api_gateway_id)
            raise SystemExit  # pylint: disable=W0707


def setup_logging(config_path: str = "logging_config.json"):
    '''Consumes the file at config_path (assumes json) and loads as the logger configuration.

    Args:
        config_path: Absolute or relative path to config file.

    Returns:
        None
    '''
    config_file = pathlib.Path(config_path)
    with open(config_file, encoding="utf-8") as f_in:
        logging_config: dict = json.load(f_in)
    logging.config.dictConfig(config=logging_config)


def parse_arguments() -> argparse.Namespace:
    '''Parse command line arguments and return

    Args:
        None
    
    Returns:
        argparse.Namespace
    '''
    parser = argparse.ArgumentParser(
        prog="FireProx",
        description="FireProx API Gateway Manager",
    )

    auth_group = parser.add_mutually_exclusive_group(required=True)

    auth_group.add_argument(
        "--aws-profile",
        type=str,
        metavar="PROFILE NAME",
        dest="aws_profile",
        default=None,
    )

    auth_group.add_argument(
        "--aws-access-key-id",
        type=str,
        dest="aws_access_key_id",
        default=None,
    )

    auth_group.add_argument(
        "--use-env-vars",
        action='store_true',
        dest="use_env_vars",
        default=None,
    )

    auth_group.add_argument(
        "--use-instance-profile",
        action='store_true',
        dest="use_instance_profile",
        default=None,
    )

    parser.add_argument(
        "--aws-secret-access-key",
        type=str,
        dest="aws_secret_access_key",
        default=None,
    )

    parser.add_argument(
        "--aws-session-token",
        type=str,
        dest="aws_session_token",
        default=None,
    )

    parser.add_argument(
        "--aws-region-name",
        type=str,
        dest="aws_region_name",
        default=None,
    )

    command_subparser = parser.add_subparsers(dest="command")

    command_subparser.add_parser("list")

    create_subcommand = command_subparser.add_parser("create")
    create_subcommand.add_argument(
        "--target-url",
        type=str,
        required=True,
        dest="target_url",
    )

    update_subcommand = command_subparser.add_parser("update")
    update_subcommand.add_argument(
        "--api-gateway-id",
        type=str,
        required=True,
        dest="api_gateway_id",
    )
    update_subcommand.add_argument(
        "--target-url",
        type=str,
        required=True,
        dest="target_url",
    )

    delete_subcommand = command_subparser.add_parser("delete")
    delete_subcommand.add_argument(
        "--api-gateway-id",
        type=str,
        required=True,
        dest="api_gateway_id",
    )

    return parser.parse_args()


def main():
    '''Parse arguments and execute desired command.

    Args:
        None

    Returns:
        None
    '''

    args = parse_arguments()

    if not args.aws_access_key_id and (args.aws_secret_access_key or args.aws_session_token):
        logger.warning(
            "AWS Secret Acccess Key and/or Session Token supplied with alternative authentication method. "
            "The secret key and token will be ignored."
        )

    logger.debug("Successfully parsed arguments", extra=vars(args))

    if not args.command:
        logger.error("No command supplied.")
        raise SystemExit

    fp = FireProx(**vars(args))

    match fp.command:
        case "list":
            fp.list_api()
        case "create":
            fp.create_api(target_url=args.target_url)
        case "delete":
            fp.delete_api(api_gateway_id=args.api_gateway_id)
        case "update":
            fp.update_api(target_url=args.target_url, api_gateway_id=args.api_gateway_id)


if __name__ == "__main__":
    setup_logging()
    main()
