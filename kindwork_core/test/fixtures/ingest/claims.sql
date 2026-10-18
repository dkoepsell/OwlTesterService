-- Claims schema
CREATE TABLE members (
  member_id varchar(20) PRIMARY KEY,
  full_name text NOT NULL
);
CREATE TABLE claims (
  claim_id bigint PRIMARY KEY,
  member_id varchar(20) REFERENCES members(member_id),
  claim_status varchar(12) NOT NULL,
  submitted_at timestamp,
  amount numeric(12,2)
);
COMMENT ON TABLE claims IS 'A request for payment under a policy.';
