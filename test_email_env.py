"""Environment configuration regression checks; no real email is sent."""
import os
import tempfile
import unittest
from unittest.mock import patch
import storage


class EmailEnvironment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        clean = {k:v for k,v in os.environ.items() if not k.startswith('FRAMEFORGE_SMTP_')}
        clean['FRAMEFORGE_DATA'] = self.tmp.name
        self.env = patch.dict(os.environ, clean, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_complete_configuration_and_saved_precedence(self):
        storage.set_pref('smtp', {'host':'old.example', 'enabled':False})
        values = dict(ENABLED='true', HOST='mail.example', PORT='465', TLS='ssl',
                      USERNAME='user', SENDER='a@example.com', RECIPIENTS='b@example.com,c@example.com',
                      ON_FAILURE='false', ON_FINISHED='yes', PASSWORD='test-secret')
        with patch.dict(os.environ, {'FRAMEFORGE_SMTP_'+k:v for k,v in values.items()}):
            config = storage.validate_mail(storage.mail_settings(), True)
            self.assertEqual(config['host'], 'mail.example')
            self.assertEqual(config['port'], 465)
            self.assertTrue(config['enabled'])
            self.assertFalse(config['onFailure'])
            self.assertTrue(config['onFinished'])
            public = storage.public_mail()
            self.assertTrue(public['settings']['hasPassword'])
            self.assertNotIn('test-secret', str(public))
            self.assertEqual(storage.get_pref('smtp')['host'], 'old.example')
        self.assertEqual(storage.mail_settings()['host'], 'old.example')

    def test_blank_fallback_and_explicit_false(self):
        storage.set_pref('smtp', {'enabled':True,'host':'saved.example'})
        with patch.dict(os.environ, {'FRAMEFORGE_SMTP_HOST':'', 'FRAMEFORGE_SMTP_ENABLED':'false'}):
            self.assertEqual(storage.mail_settings()['host'], 'saved.example')
            self.assertFalse(storage.mail_settings()['enabled'])

    def test_invalid_values_fail_without_exposing_values(self):
        for key,value in [('PORT','nope'),('PORT','0'),('TLS','invalid'),('ENABLED','invalid')]:
            with self.subTest(key=key,value=value), patch.dict(os.environ, {'FRAMEFORGE_SMTP_'+key:value}):
                with self.assertRaises(ValueError): storage.mail_settings()

    def test_environment_password_overrides_session(self):
        storage.set_pref('smtp',dict(enabled=True,host='mail.example',sender='a@example.com',recipients='b@example.com'))
        previous = storage.SECRET
        storage.SECRET = 'session-password'
        try:
            with patch.dict(os.environ, {'FRAMEFORGE_SMTP_PASSWORD':'env-password'}), patch.object(storage, 'deliver') as deliver, patch.object(storage.threading, 'Thread') as thread:
                thread.side_effect = lambda target, **kwargs: type('Immediate', (), {'start': lambda self: target()})()
                storage.notify('finished','test','body')
                self.assertEqual(deliver.call_args.args[1], 'env-password')
        finally:
            storage.SECRET = previous


if __name__ == '__main__':
    unittest.main()
