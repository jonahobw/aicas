"""Utility functions including email."""

# pylint: disable=too-many-arguments, invalid-name, too-few-public-methods

from pathlib import Path
from smtplib import SMTPException, SMTP_SSL
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger("utils")


class Email_Sender:
    """Stores email sender, reciever, and pw."""

    def __init__(
        self,
        sender: str = None,
        reciever: str = None,
        pw: str = None,
        send: bool = True,
        **kwargs
    ) -> None:
        """Store email params."""

        self.sender = sender
        self.reciever = reciever
        self.pw = self.retrieve_pw(pw)
        self.send = send
        if self.send is not None:
            logger.info("Email settings: send set to %s", send)
        # dummy function in case an argument is not provided:
        if None in (sender, reciever, pw):
            logger.warning(
                "At least one of email sender, reciever, or pw was not"
                "specified, will not send any emails."
            )
            self.email = lambda subject, content: 0
        else:
            self.email = self._email

    def retrieve_pw(self, file: str=None) -> str:
        """Retrieves the gmail password from a file."""

        if file is None:
            return None
        with open(Path()/file, 'r') as pw_file:
            pw = pw_file.read()
        return pw

    def _email(self, subject, content=""):
        """Send an email."""
        email(
            content=content,
            subject=subject,
            sender=self.sender,
            reciever=self.reciever,
            pw=self.pw,
            send=self.send,
        )


def email(
    content: str,
    subject: str,
    sender: str,
    reciever: str,
    pw: str = None,
    send: bool = True,
) -> None:
    """
    Sends an email from a gmail account.

    :param content: the message inside the email.
    :param subject: the subject line.
    :param sender: the sending email address.
    :param reciever: the destination email address.
    :param pw: the gmail password for the sending email address.
    :param send: will only send an email if this is true.

    :return: None
    """

    if not send:
        return

    message = MIMEMultipart()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = reciever
    message.attach(MIMEText(content, "plain"))

    try:
        context = ssl.create_default_context()
        with SMTP_SSL(host="smtp.gmail.com", port=465, context=context) as server:
            server.login(sender, pw)
            server.sendmail(sender, reciever, message.as_string())
            server.quit()
    except SMTPException as e:
        logger.warning("Error while trying to send email: \n%s", e)

def timer(time_in_s):
    hours, rem = divmod(time_in_s, 3600)
    minutes, seconds = divmod(rem, 60)
    return "{:0>2}:{:0>2}:{:0>2}".format(int(hours),int(minutes),int(seconds))


def generate_permutations(list_args: dict) -> list:
    """
    Given several parameters values which each can take multiple values, return all permutations
    of the parameters.

    example input:
    {
        "model_type": ["vgg_bn_drop", "resnet20"],
        "prune_method": ["RandomPruning", "GlobalMagWeight"]
    }

    example output:
    [
        {
            "model_type": "vgg_bn_drop",
            "prune_method": "RandomPruning",
        },
        {
            "model_type": "vgg_bn_drop",
            "prune_method": "GlobalMagWeight",
        },
        {
            "model_type": "resnet20",
            "prune_method": "RandomPruning",
        },
        {
            "model_type": "resnet20",
            "prune_method": "GlobalMagWeight",
        }
    ]

    :param list_args: a dictionary of the parameters formatted as {"parameter_name": [parameter_values]}.

    :return: a list of dictionaries, where each dictionary is a permutation of the possible
        parameter combinations.
    """

    #Todo there is a bug where if the first list has more than 2 elements, multiple copies of the same element
    # get added.  the base case needs to be fixed.


    permutations = []

    while(len(list_args) > 0):
        parameter, vals = list_args.popitem()     # popitem returns a tuple (key, val)
        for val in vals:
            temp = permutations.copy()  # must do this to prevent infinite loop
            for permutation in temp:
                if parameter in permutation:
                    new_permutation = permutation.copy()
                    new_permutation[parameter] = val
                    permutations.append(new_permutation)
                else:
                    permutation[parameter] = val
            if len(permutations) == 0:
                permutations.append({parameter: val})
    return permutations


if __name__ == "__main__":
    print(f"Testing on module {Path.cwd()}")
    example =     {
        "model_type": ["vgg_bn_drop"],   #, "resnet20"],
        #"prune_method": ["RandomPruning"],
        "finetune_iterations": [10, 20, 40]
    }
    a = generate_permutations(example)
    import json
    print(json.dumps(a, indent=4))