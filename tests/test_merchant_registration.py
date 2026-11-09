import unittest
from merchant_registration import register, validate, REGISTER_URL

class MerchantRegistrationTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(validate('778399976', 'tech@example.com'), ('778399976', 'tech@example.com'))
        for id in ('abc', '0', '123;DROP TABLE x'):
            with self.assertRaises(ValueError): validate(id, 'tech@example.com')
        with self.assertRaises(ValueError): validate('778399976','bad-email')

    def test_register_resource_and_payload(self):
        calls=[]
        def post(url,payload):
            calls.append((url,payload))
            return {'name':'accounts/778399976/developerRegistration','gcpIds':['956657049463']}
        result=register(post,'778399976','tech@example.com')
        self.assertEqual(calls,[(REGISTER_URL.format(account='778399976'),{'developerEmail':'tech@example.com'})])
        self.assertEqual(result['gcp_ids'],['956657049463'])

    def test_does_not_accept_missing_or_mismatched_confirmation(self):
        for data in ({}, {'name':'accounts/1234/developerRegistration','gcpIds':['5']},
                     {'name':'accounts/778399976/developerRegistration','gcpIds':[]}):
            with self.assertRaises(ValueError):register(lambda url,payload:data,'778399976','tech@example.com')

if __name__=='__main__':unittest.main()
